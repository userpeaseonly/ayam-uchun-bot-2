import asyncio
import runpy
import sqlite3
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import RefundStarPayment
from aiogram.types import Update
from aiohttp.test_utils import TestClient, TestServer

import config
from scripts.database.db import get_db_connection, init_db
from services import stars_payments as stars
from services.platform_service import PlatformError, one
from services.telegram_auth import make_session
from services.web_app import create_web_app, PAYMENT_BOT_KEY


@pytest.fixture
async def payment_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_PATH', str(tmp_path / 'payments.sqlite3'))
    monkeypatch.setattr(config, 'BOT_TOKEN', '123456:fake-stars-token')
    monkeypatch.setattr(config, 'MINI_APP_URL', 'https://mini.example')
    monkeypatch.setattr(config, 'ADMIN_IDS', [111])
    monkeypatch.setattr(config, 'TELEGRAM_TEST_ENVIRONMENT', True)
    monkeypatch.setattr(config, 'STARS_TEST_PAYMENTS_ENABLED', True)
    monkeypatch.setattr(config, 'STARS_ALLOW_LIVE_TEST_PAYMENTS', False)
    monkeypatch.setattr(config, 'PAYMENT_SUPPORT_USERNAME', 'ExampleSupport')
    await init_db()
    return SimpleNamespace(create_invoice_link=AsyncMock(return_value='https://t.me/$fixture-invoice'),
        refund_star_payment=AsyncMock(return_value=True), get_star_transactions=AsyncMock(return_value=SimpleNamespace(transactions=[])))


async def order(bot, user=111, key=None):
    return await stars.create_test_order(user, key or uuid.uuid4().hex, stars.TERMS_VERSION, True, bot)


async def pay(item, charge='charge-1', **overrides):
    return await stars.record_payment(**({'user_id': 111, 'payload': stars.PREFIX + item['id'], 'currency': 'XTR', 'amount': 1, 'charge_id': charge} | overrides))


@pytest.mark.asyncio
async def test_disabled_live_nonadmin_and_terms_cannot_create_orders(payment_db, monkeypatch):
    bot = payment_db
    for setting, value in [('STARS_TEST_PAYMENTS_ENABLED', False), ('TELEGRAM_TEST_ENVIRONMENT', False), ('PAYMENT_SUPPORT_USERNAME', ''), ('PAYMENT_SUPPORT_USERNAME', 'bad/user')]:
        with monkeypatch.context() as patch:
            patch.setattr(config, setting, value)
            with pytest.raises(PlatformError):
                await order(bot)
    with pytest.raises(PlatformError):
        await order(bot, user=222)
    for version, accepted in [(stars.TERMS_VERSION, False), ('old-terms', True), (stars.TERMS_VERSION, 'true')]:
        with pytest.raises(PlatformError):
            await stars.create_test_order(111, uuid.uuid4().hex, version, accepted, bot)
    bot.create_invoice_link.assert_not_awaited()
    monkeypatch.setattr(config, 'TELEGRAM_TEST_ENVIRONMENT', False)
    monkeypatch.setattr(config, 'STARS_ALLOW_LIVE_TEST_PAYMENTS', True)
    assert (await order(bot))['environment'] == 'live'


@pytest.mark.asyncio
async def test_concurrent_retries_create_one_native_invoice_and_no_entitlement(payment_db):
    key = uuid.uuid4().hex
    values = await asyncio.gather(*(order(payment_db, key=key) for _ in range(8)))
    assert len({value['id'] for value in values}) == 1
    payment_db.create_invoice_link.assert_awaited_once()
    kwargs = payment_db.create_invoice_link.await_args.kwargs
    assert kwargs['currency'] == 'XTR' and kwargs['provider_token'] == ''
    assert len(kwargs['prices']) == 1 and kwargs['prices'][0].amount == 1
    async with get_db_connection() as db:
        assert (await one(db, 'SELECT COUNT(*) n FROM payment_orders'))['n'] == 1
        assert (await one(db, 'SELECT COUNT(*) n FROM tests'))['n'] == 0
        assert (await one(db, 'SELECT COUNT(*) n FROM timed_attempts'))['n'] == 0
    await init_db()
    assert (await order(payment_db, key=key))['id'] == values[0]['id']


@pytest.mark.asyncio
async def test_invoice_failure_retry_preserves_order_and_hides_provider_errors(payment_db):
    payment_db.create_invoice_link.side_effect = [RuntimeError('secret-token-must-not-leak'), 'https://t.me/$retry-invoice']
    key = uuid.uuid4().hex
    with pytest.raises(PlatformError) as caught:
        await order(payment_db, key=key)
    assert 'secret-token' not in str(caught.value)
    item = await order(payment_db, key=key)
    assert item['status'] == 'invoice_ready'
    assert len((await stars.history(111))['orders']) == 1


@pytest.mark.asyncio
async def test_checkout_checks_owner_amount_currency_expiry_and_reserves_once(payment_db):
    item = await order(payment_db)
    payload = stars.PREFIX + item['id']
    for user, currency, amount in [(222, 'XTR', 1), (111, 'UZS', 1), (111, 'XTR', 1000), (111, 'XTR', True)]:
        with pytest.raises(PlatformError):
            await stars.validate_checkout(user, payload, currency, amount, 'query-1')
    results = await asyncio.gather(*(stars.validate_checkout(111, payload, 'XTR', 1, query) for query in ['query-1', 'query-2']), return_exceptions=True)
    assert sum(value is None for value in results) == 1
    saved = await stars.owned_order(item['id'], 111)
    await stars.validate_checkout(111, payload, 'XTR', 1, saved['pre_checkout_id'])
    # A browser callback / pre-checkout approval alone never counts as payment.
    assert (await stars.owned_order(item['id'], 111))['status'] == 'checkout'
    async with get_db_connection() as db:
        await db.execute('UPDATE payment_orders SET expires_at=0 WHERE id=?', (item['id'],))
        await db.commit()
    with pytest.raises(PlatformError):
        await stars.validate_checkout(111, payload, 'XTR', 1, saved['pre_checkout_id'])


@pytest.mark.asyncio
async def test_locked_database_rejects_checkout_with_time_to_answer_telegram(payment_db):
    item = await order(payment_db)
    async with get_db_connection() as blocking:
        await blocking.execute('BEGIN IMMEDIATE')
        started = time.monotonic()
        with pytest.raises(sqlite3.OperationalError, match='locked'):
            await stars.validate_checkout(111, stars.PREFIX + item['id'], 'XTR', 1, 'busy-query')
        assert time.monotonic() - started < 5
        await blocking.rollback()
    assert (await stars.owned_order(item['id'], 111))['status'] == 'invoice_ready'


@pytest.mark.asyncio
async def test_late_success_after_disable_or_expiry_is_recorded_once(payment_db, monkeypatch):
    item = await order(payment_db)
    async with get_db_connection() as db:
        await db.execute('UPDATE payment_orders SET expires_at=0 WHERE id=?', (item['id'],))
        await db.commit()
    monkeypatch.setattr(config, 'STARS_TEST_PAYMENTS_ENABLED', False)
    monkeypatch.setattr(config, 'ADMIN_IDS', [])
    await asyncio.gather(*(pay(item) for _ in range(8)))
    assert (await stars.owned_order(item['id'], 111))['status'] == 'paid'
    assert await stars.visible(111)
    async with get_db_connection() as db:
        assert (await one(db, 'SELECT COUNT(*) n FROM star_receipts'))['n'] == 1
    assert not (await stars.history(111))['settings']['enabled']
    await stars.request_refund(item['id'], 111)
    await stars.refund_pending(payment_db)
    assert (await stars.owned_order(item['id'], 111))['status'] == 'refunded'
    await pay(item)  # Late duplicate cannot resurrect a refunded order.
    assert (await stars.owned_order(item['id'], 111))['status'] == 'refunded'


@pytest.mark.asyncio
async def test_extra_and_mismatched_payments_refund_without_rewriting_primary(payment_db):
    item = await order(payment_db)
    await pay(item)
    await pay(item, charge='extra-charge')
    await pay(item, charge='wrong-owner', user_id=222)
    await pay(item, charge='wrong-amount', amount=4)
    await pay(item, charge='orphan', payload=stars.PREFIX + 'f' * 32)
    assert (await stars.owned_order(item['id'], 111))['charge_id'] == 'charge-1'
    await stars.refund_pending(payment_db)
    assert payment_db.refund_star_payment.await_count == 4
    assert (await stars.owned_order(item['id'], 111))['status'] == 'paid'
    with pytest.raises(PlatformError):
        await pay(item, amount=2)  # Same charge ID, inconsistent receipt.
    with pytest.raises(PlatformError):
        await pay(item, charge='usd', currency='USD')


@pytest.mark.asyncio
async def test_orphan_payer_retains_history_after_pilot_disabled(payment_db, monkeypatch):
    await stars.record_payment(222, stars.PREFIX + 'f' * 32, 'XTR', 1, 'orphan-only')
    monkeypatch.setattr(config, 'STARS_TEST_PAYMENTS_ENABLED', False)
    assert await stars.visible(222)
    history = await stars.history(222)
    assert not history['orders'] and not history['settings']['enabled']
    assert history['additional_payments'][0]['status'] == 'refund_pending'
    await stars.refund_pending(payment_db)
    assert (await stars.history(222))['additional_payments'][0]['status'] == 'refunded'


@pytest.mark.asyncio
async def test_refund_before_success_and_duplicate_refunds_are_idempotent(payment_db):
    item = await order(payment_db)
    await pay(item, refunded=True)
    await pay(item)
    await stars.request_refund(item['id'], 111)
    await stars.refund_pending(payment_db)
    payment_db.refund_star_payment.assert_not_awaited()
    assert (await stars.owned_order(item['id'], 111))['status'] == 'refunded'


@pytest.mark.asyncio
async def test_refund_worker_recovers_network_failure_and_already_refunded(payment_db):
    item = await order(payment_db)
    await pay(item)
    with pytest.raises(PlatformError):
        await stars.request_refund(item['id'], 222)
    payment_db.refund_star_payment.side_effect = [TimeoutError(), TelegramBadRequest(method=RefundStarPayment(user_id=111, telegram_payment_charge_id='charge-1'), message='Bad Request: CHARGE_ALREADY_REFUNDED')]
    await stars.request_refund(item['id'], 111)
    await stars.refund_pending(payment_db)
    assert (await stars.owned_order(item['id'], 111))['status'] == 'refund_pending'
    await init_db()  # Restart does not discard the pending refund.
    await stars.request_refund(item['id'], 111)  # Manual retry clears backoff.
    await stars.refund_pending(payment_db)
    assert (await stars.owned_order(item['id'], 111))['status'] == 'refunded'


def transaction(item, charge, *, refund=False, user=111):
    partner = SimpleNamespace(type='user', transaction_type='invoice_payment', invoice_payload=stars.PREFIX + item['id'], user=SimpleNamespace(id=user))
    return SimpleNamespace(id=charge, amount=1, nanostar_amount=None, source=None if refund else partner, receiver=partner if refund else None)


@pytest.mark.asyncio
async def test_transaction_history_recovers_missing_updates_including_late_refunds(payment_db):
    item = await order(payment_db)
    payment_db.get_star_transactions.return_value = SimpleNamespace(transactions=[transaction(item, 'recovered')])
    await stars.reconcile(payment_db)
    assert (await stars.owned_order(item['id'], 111))['status'] == 'paid'
    payment_db.get_star_transactions.return_value = SimpleNamespace(transactions=[transaction(item, 'recovered', refund=True), transaction(item, 'recovered')])
    await stars.reconcile(payment_db)
    assert (await stars.owned_order(item['id'], 111))['status'] == 'refunded'


@pytest.mark.asyncio
async def test_history_scan_paginates_and_ignores_other_bot_revenue(payment_db):
    item = await order(payment_db)
    unrelated = SimpleNamespace(source=SimpleNamespace(type='fragment'), receiver=None)
    payment_db.get_star_transactions.side_effect = [SimpleNamespace(transactions=[unrelated] * 100), SimpleNamespace(transactions=[transaction(item, 'page-two')])]
    await stars.reconcile(payment_db)
    assert [call.kwargs['offset'] for call in payment_db.get_star_transactions.await_args_list] == [0, 100]
    assert (await stars.owned_order(item['id'], 111))['status'] == 'paid'


@pytest.mark.asyncio
async def test_bad_history_receipt_does_not_block_recovery_of_other_payments(payment_db):
    first, second = await order(payment_db), await order(payment_db)
    await pay(first, charge='existing')
    payment_db.get_star_transactions.return_value = SimpleNamespace(transactions=[
        transaction(first, 'existing', user=222), transaction(second, 'recover-next')])
    await stars.reconcile(payment_db)
    assert (await stars.owned_order(second['id'], 111))['status'] == 'paid'


@pytest.mark.asyncio
async def test_bot_and_environment_isolate_history_invoices_and_refunds(payment_db, monkeypatch):
    item = await order(payment_db)
    await pay(item)
    for field, value in [('BOT_TOKEN', '777777:other-token'), ('TELEGRAM_TEST_ENVIRONMENT', False)]:
        with monkeypatch.context() as patch:
            patch.setattr(config, field, value)
            assert not (await stars.history(111))['orders']
            with pytest.raises(PlatformError):
                await stars.request_refund(item['id'], 111)
            await stars.refund_pending(payment_db)
            payment_db.refund_star_payment.assert_not_awaited()


@pytest.mark.asyncio
async def test_api_auth_csrf_ownership_and_fixed_amount(payment_db):
    app = create_web_app()
    app[PAYMENT_BOT_KEY] = payment_db
    async with TestClient(TestServer(app)) as client:
        assert (await client.get('/api/payments')).status == 401
        client.session.cookie_jar.update_cookies({'ayam_session': make_session({'id': 111, 'first_name': 'Admin'})})
        data = {'request_key': uuid.uuid4().hex, 'accepted_terms': True, 'terms_version': stars.TERMS_VERSION, 'amount': 1000, 'currency': 'UZS', 'user_id': 222}
        assert (await client.post('/api/payments/stars/test', json=data, headers={'Origin': 'https://evil.example'})).status == 403
        response = await client.post('/api/payments/stars/test', json=data)
        assert response.status == 200
        item = await response.json()
        assert item['amount'] == 1 and item['currency'] == 'XTR'
        assert (await stars.owned_order(item['id'], 111))['user_id'] == 111
        assert (await (await client.get('/api/me')).json())['show_payments']
        client.session.cookie_jar.update_cookies({'ayam_session': make_session({'id': 222})})
        assert (await client.post('/api/payments/stars/test', json=data)).status == 403
        assert (await client.get('/api/payments/orders/' + item['id'])).status == 404
        assert (await client.post('/api/payments/orders/' + item['id'] + '/refund')).status == 404
        assert not (await (await client.get('/api/payments')).json())['orders']
        assert not (await (await client.get('/api/me')).json())['show_payments']


@pytest.mark.asyncio
async def test_payment_router_precedes_catchall_fsm_and_checks_precheckout(payment_db):
    from handlers import payments
    bot = Bot(config.BOT_TOKEN)
    replies = AsyncMock(return_value=None)
    bot.session = replies
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(payments.router)
    fallback = Router()
    caught = AsyncMock()
    async def catch_message(message):
        await caught(message)
    fallback.message.register(catch_message, StateFilter('*'))
    dp.include_router(fallback)
    item = await order(payment_db)
    message = {'message_id': 1, 'date': int(time.time()), 'chat': {'id': 111, 'type': 'private'},
               'from': {'id': 111, 'is_bot': False, 'first_name': 'Admin'},
               'successful_payment': {'currency': 'XTR', 'total_amount': 1, 'invoice_payload': stars.PREFIX + item['id'], 'telegram_payment_charge_id': 'routed', 'provider_payment_charge_id': ''}}
    await dp.feed_update(bot, Update.model_validate({'update_id': 1, 'message': message}))
    assert (await stars.owned_order(item['id'], 111))['status'] == 'paid'
    caught.assert_not_awaited()
    await dp.feed_update(bot, Update.model_validate({'update_id': 2, 'pre_checkout_query': {
        'id': 'wrong-buyer', 'from': {'id': 222, 'is_bot': False, 'first_name': 'Other'}, 'currency': 'XTR', 'total_amount': 1, 'invoice_payload': stars.PREFIX + item['id']}}))
    assert replies.await_args.args[1].ok is False
    fresh = await order(payment_db)
    await dp.feed_update(bot, Update.model_validate({'update_id': 3, 'pre_checkout_query': {
        'id': 'valid-buyer', 'from': {'id': 111, 'is_bot': False, 'first_name': 'Admin'}, 'currency': 'XTR', 'total_amount': 1, 'invoice_payload': stars.PREFIX + fresh['id']}}))
    assert replies.await_args.args[1].ok is True
    assert (await stars.owned_order(fresh['id'], 111))['status'] == 'checkout'
    message.pop('successful_payment')
    message['refunded_payment'] = {'currency': 'XTR', 'total_amount': 1, 'invoice_payload': stars.PREFIX + item['id'], 'telegram_payment_charge_id': 'routed'}
    await dp.feed_update(bot, Update.model_validate({'update_id': 4, 'message': message}))
    assert (await stars.owned_order(item['id'], 111))['status'] == 'refunded'
    caught.assert_not_awaited()
    # Future non-pilot Stars products must not be captured/refunded by this pilot.
    message.pop('refunded_payment')
    message['successful_payment'] = {'currency': 'XTR', 'total_amount': 2, 'invoice_payload': 'other-product', 'telegram_payment_charge_id': 'other-charge', 'provider_payment_charge_id': ''}
    await dp.feed_update(bot, Update.model_validate({'update_id': 5, 'message': message}))
    caught.assert_awaited_once()
    async with get_db_connection() as db:
        assert not await one(db, "SELECT charge_id FROM star_receipts WHERE charge_id='other-charge'")
    await dp.storage.close()


def test_flags_default_off_and_test_server_uses_real_telegram_test_endpoint(monkeypatch):
    from aiogram.client.telegram import TEST, PRODUCTION
    assert '/test/getMe' in TEST.api_url('123:fake', 'getMe')
    assert '/test/' not in PRODUCTION.api_url('123:fake', 'getMe')
    for name in ['TELEGRAM_TEST_ENVIRONMENT', 'STARS_TEST_PAYMENTS_ENABLED', 'STARS_ALLOW_LIVE_TEST_PAYMENTS', 'PAYMENT_SUPPORT_USERNAME', 'BROWSER_APP_URL', 'WEB_TEST_PAYMENTS_ENABLED', 'WEB_ALLOW_LIVE_TEST_PAYMENTS']:
        monkeypatch.delenv(name, raising=False)
    # Evaluate configuration without reading real dotenv files.
    monkeypatch.setattr('dotenv.load_dotenv', lambda: None)
    defaults = runpy.run_path('config.py')
    assert defaults['TELEGRAM_TEST_ENVIRONMENT'] is False
    assert defaults['STARS_TEST_PAYMENTS_ENABLED'] is False
    assert defaults['STARS_ALLOW_LIVE_TEST_PAYMENTS'] is False
    assert defaults['PAYMENT_SUPPORT_USERNAME'] == ''
    assert defaults['BROWSER_APP_URL'] == ''
    assert defaults['WEB_TEST_PAYMENTS_ENABLED'] is False
    assert defaults['WEB_ALLOW_LIVE_TEST_PAYMENTS'] is False
