import asyncio
import base64
import hashlib
import uuid
from urllib.parse import urlsplit, parse_qs

import pytest
from aiohttp.test_utils import TestClient, TestServer
import config
from scripts.database.db import get_db_connection, init_db
from services import web_payments as payments, click_payments as click, payme_payments as payme, browser_auth
from services.platform_service import PlatformError, one
from services.telegram_auth import make_session, read_session_context
from services.web_app import create_web_app, BOT_USERNAME_KEY


@pytest.fixture
async def merchant_db(tmp_path, monkeypatch):
    values = dict(DB_PATH=str(tmp_path / 'merchants.sqlite3'), BOT_TOKEN='123456:fixture-only',
        MINI_APP_URL='https://mini.example', BROWSER_APP_URL='https://web.example', ADMIN_IDS=[111],
        WEB_TEST_PAYMENTS_ENABLED=True, WEB_ALLOW_LIVE_TEST_PAYMENTS=False, PAYMENT_SUPPORT_USERNAME='ExampleSupport',
        CLICK_ENVIRONMENT='test', CLICK_TEST_SERVICE_ID='234', CLICK_TEST_MERCHANT_ID='567', CLICK_TEST_SECRET_KEY='click-fixture-secret',
        CLICK_SERVICE_ID='998', CLICK_MERCHANT_ID='997', CLICK_SECRET_KEY='live-click-fixture',
        PAYME_ENVIRONMENT='test', PAYME_TEST_MERCHANT_ID='merchant-test', PAYME_TEST_KEY='payme-fixture-secret',
        PAYME_MERCHANT_ID='merchant-live', PAYME_KEY='live-payme-fixture')
    for key, value in values.items():
        monkeypatch.setattr(config, key, value)
    await init_db()


async def order(provider='click', key=None, user=111):
    return await payments.create_order(user, provider, key or uuid.uuid4().hex, payments.TERMS_VERSION, True)


def click_data(item, action=0, **updates):
    data = dict(click_trans_id='1234567', service_id='234', click_paydoc_id='121212',
                merchant_trans_id=item['id'], amount='1000.00', action=str(action), error='0',
                error_note='Success', sign_time='2026-11-24 12:00:00')
    data.update(updates)
    text = data['click_trans_id'] + data['service_id'] + 'click-fixture-secret' + data['merchant_trans_id']
    if action:
        text += data.get('merchant_prepare_id', '')
    text += data['amount'] + data['action'] + data['sign_time']
    data['sign_string'] = hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()
    return data


def authorization(secret='payme-fixture-secret'):
    return 'Basic ' + base64.b64encode(('Paycom:' + secret).encode()).decode()


async def rpc(method, params, *, auth=None, env='test'):
    return await payme.process(env, authorization() if auth is None else auth, dict(id=7, method=method, params=params))


def create_params(item, tx='payme-1'):
    return dict(id=tx, time=payments.now_ms(), account={'order_id': item['id']}, amount=100000)


@pytest.mark.asyncio
async def test_orders_fail_closed_until_merchant_flags_and_terms_ready(merchant_db, monkeypatch):
    for key, value in [('WEB_TEST_PAYMENTS_ENABLED', False), ('BROWSER_APP_URL', ''),
                       ('PAYMENT_SUPPORT_USERNAME', ''), ('CLICK_TEST_SECRET_KEY', ''), ('CLICK_ENVIRONMENT', 'live')]:
        with monkeypatch.context() as patch:
            patch.setattr(config, key, value)
            with pytest.raises(PlatformError):
                await order()
    with pytest.raises(PlatformError):
        await order(user=222)
    for version, accepted in [('old', True), (payments.TERMS_VERSION, 'true')]:
        with pytest.raises(PlatformError):
            await payments.create_order(111, 'click', uuid.uuid4().hex, version, accepted)
    with monkeypatch.context() as patch:
        patch.setattr(config, 'PAYME_TEST_KEY', '')
        assert payments.available('click', 111) and not payments.available('payme', 111)
    monkeypatch.setattr(config, 'CLICK_ENVIRONMENT', 'live')
    monkeypatch.setattr(config, 'WEB_ALLOW_LIVE_TEST_PAYMENTS', True)
    assert (await order())['environment'] == 'live'


@pytest.mark.asyncio
async def test_disabled_checkout_hides_unused_panel_but_preserves_existing_history(merchant_db, monkeypatch):
    assert await payments.visible(111)
    assert not await payments.visible(222)
    monkeypatch.setattr(config, 'WEB_TEST_PAYMENTS_ENABLED', False)
    assert not await payments.visible(111)
    with pytest.raises(PlatformError):
        await order()

    monkeypatch.setattr(config, 'WEB_TEST_PAYMENTS_ENABLED', True)
    item = await order()
    monkeypatch.setattr(config, 'WEB_TEST_PAYMENTS_ENABLED', False)
    assert await payments.visible(111)
    history = await payments.history(111)
    assert history['orders'][0]['id'] == item['id']
    assert 'checkout_url' not in history['orders'][0]
    assert not any(provider['enabled'] for provider in history['settings']['providers'])
    assert not await payments.visible(222)


@pytest.mark.asyncio
async def test_concurrent_orders_and_checkout_money_units_are_server_owned(merchant_db):
    key = uuid.uuid4().hex
    orders = await asyncio.gather(*(order(key=key) for _ in range(8)))
    assert len({item['id'] for item in orders}) == 1
    url = urlsplit(orders[0]['checkout_url'])
    assert url.netloc == 'my.click.uz'
    args = parse_qs(url.query)
    assert args['amount'] == ['1000.00'] and args['service_id'] == ['234']
    payme_order = await order('payme')
    url = urlsplit(payme_order['checkout_url'])
    assert url.netloc == 'test.paycom.uz'
    text = base64.b64decode(url.path[1:]).decode()
    assert ';a=100000;' in text and 'ac.order_id=' + payme_order['id'] in text
    await init_db()
    assert (await order(key=key))['id'] == orders[0]['id']
    async with get_db_connection() as db:
        assert (await one(db, 'SELECT COUNT(*) n FROM web_payment_orders'))['n'] == 2
        assert (await one(db, 'SELECT COUNT(*) n FROM submissions'))['n'] == 0


@pytest.mark.asyncio
async def test_click_auth_amount_service_prepare_and_transaction_binding(merchant_db):
    item = await order()
    data = click_data(item)
    data['amount'] = '1.00'  # Forged after signing.
    assert (await click.process('test', data, 0))['error'] == -1
    for amount in ('1.00', '1000.001', 'NaN', '1e3'):
        assert (await click.process('test', click_data(item, amount=amount), 0))['error'] == -2
    assert (await click.process('test', click_data(item, service_id='999'), 0))['error'] == -1
    assert (await click.process('live', click_data(item), 0))['error'] == -1
    assert (await click.process('test', click_data(item, error='1'), 0))['error'] == -8
    assert (await click.process('test', click_data(item) | {'sign_string': 'я' * 32}, 0))['error'] == -1
    assert (await click.process('test', click_data(item, action=1, merchant_prepare_id='1'), 1))['error'] == -6
    first = await click.process('test', click_data(item), 0)
    assert first['error'] == 0 and isinstance(first['merchant_prepare_id'], int)
    assert (await click.process('test', click_data(item, 1, merchant_prepare_id='999'), 1))['error'] == -6
    other = await order()
    assert (await click.process('test', click_data(other), 0))['error'] == -6


@pytest.mark.asyncio
async def test_click_retry_races_late_completion_and_disable_preserve_receipts(merchant_db, monkeypatch):
    item = await order()
    results = await asyncio.gather(*(click.process('test', click_data(item), 0) for _ in range(8)))
    assert {r['error'] for r in results} == {0}
    assert len({r['merchant_prepare_id'] for r in results}) == 1
    async with get_db_connection() as db:
        await db.execute('UPDATE web_payment_orders SET expires_at=0 WHERE id=?', (item['id'],))
        await db.commit()
    monkeypatch.setattr(config, 'WEB_TEST_PAYMENTS_ENABLED', False)
    data = click_data(item, 1, merchant_prepare_id=str(results[0]['merchant_prepare_id']))
    assert (await click.process('test', data, 1))['error'] == 0
    await init_db()
    assert (await click.process('test', data, 1))['error'] == -4
    assert (await payments.owned_order(item['id'], 111))['status'] == 'paid'
    data = click_data(item, 1, merchant_prepare_id=data['merchant_prepare_id'], error='-9')
    assert (await click.process('test', data, 1))['error'] == -4
    assert (await payments.owned_order(item['id'], 111))['status'] == 'paid'


@pytest.mark.asyncio
async def test_click_cancel_is_durable_and_unprepared_expiry_rejects(merchant_db):
    item = await order()
    prepared = await click.process('test', click_data(item), 0)
    cancelled = click_data(item, 1, merchant_prepare_id=str(prepared['merchant_prepare_id']), error='-9')
    assert (await click.process('test', cancelled, 1))['error'] == -9
    await init_db()
    assert (await payments.owned_order(item['id'], 111))['status'] == 'cancelled'
    assert (await click.process('test', click_data(item), 0))['error'] == -9
    late = await order()
    async with get_db_connection() as db:
        await db.execute('UPDATE web_payment_orders SET expires_at=0 WHERE id=?', (late['id'],))
        await db.commit()
    assert (await click.process('test', click_data(late, click_trans_id='888'), 0))['error'] == -9


@pytest.mark.asyncio
async def test_payme_unknown_error_reason_ten_and_bot_merchant_isolation(merchant_db, monkeypatch):
    item = await order('payme')
    await rpc('CreateTransaction', create_params(item))
    for setting, value in [('BOT_TOKEN', '777777:another-fixture'), ('PAYME_TEST_MERCHANT_ID', 'another-merchant')]:
        with monkeypatch.context() as patch:
            patch.setattr(config, setting, value)
            assert (await rpc('CheckTransaction', {'id': 'payme-1'}))['error']['code'] == -31003
            assert not (await rpc('GetStatement', {'from': 0, 'to': payments.now_ms()}))['result']['transactions']
    cancelled = await rpc('CancelTransaction', {'id': 'payme-1', 'reason': 10})
    assert cancelled['result']['state'] == -1
    assert (await rpc('CheckTransaction', {'id': 'payme-1'}))['result']['reason'] == 10


@pytest.mark.asyncio
async def test_payme_auth_amount_and_account_are_required(merchant_db):
    item = await order('payme')
    params = create_params(item)
    assert (await rpc('CreateTransaction', params, auth='Basic wrong'))['error']['code'] == -32504
    assert (await rpc('CreateTransaction', params, env='live'))['error']['code'] == -32504
    assert (await rpc('CreateTransaction', params | {'amount': True}))['error']['code'] == -31001
    assert (await rpc('CreateTransaction', params | {'account': {'order_id': 'unknown'}}))['error']['code'] == -31050
    assert (await rpc('CheckPerformTransaction', params))['result']['allow']
    assert (await rpc('OtherMethod', {}))['error']['code'] == -32601


@pytest.mark.asyncio
async def test_payme_lifecycle_idempotency_refund_and_statement_survive_restart(merchant_db, monkeypatch):
    item = await order('payme')
    params = create_params(item)
    results = await asyncio.gather(*(rpc('CreateTransaction', params) for _ in range(8)))
    assert all(r['result'] == results[0]['result'] for r in results)
    assert results[0]['result']['state'] == 1
    monkeypatch.setattr(config, 'WEB_TEST_PAYMENTS_ENABLED', False)
    performed = await rpc('PerformTransaction', {'id': params['id']})
    await init_db()
    assert (await rpc('PerformTransaction', {'id': params['id']})) == performed
    assert (await payments.owned_order(item['id'], 111))['status'] == 'paid'
    statement = (await rpc('GetStatement', {'from': params['time'], 'to': params['time']}))['result']['transactions']
    assert len(statement) == 1 and statement[0]['amount'] == 100000
    assert statement[0]['account'] == {'order_id': item['id']} and statement[0]['state'] == 2
    cancelled = await rpc('CancelTransaction', {'id': params['id'], 'reason': 1})
    assert cancelled['result']['state'] == -2
    assert (await rpc('CancelTransaction', {'id': params['id'], 'reason': 2})) == cancelled
    assert (await rpc('PerformTransaction', {'id': params['id']}))['error']['code'] == -31008
    assert (await payments.owned_order(item['id'], 111))['status'] == 'refunded'


@pytest.mark.asyncio
async def test_payme_competing_ids_and_mutated_retries_cannot_double_pay(merchant_db):
    item = await order('payme')
    params = create_params(item)
    results = await asyncio.gather(rpc('CreateTransaction', params), rpc('CreateTransaction', params | {'id': 'payme-2'}))
    assert sum('result' in r for r in results) == 1
    winner = params['id'] if 'result' in results[0] else 'payme-2'
    assert (await rpc('CreateTransaction', params | {'id': winner, 'time': params['time'] + 1}))['error']['code'] == -31008
    other = await order('payme')
    assert (await rpc('CreateTransaction', params | {'id': winner, 'account': {'order_id': other['id']}}))['error']['code'] == -31008


@pytest.mark.asyncio
async def test_payme_timeout_cancellation_commits_even_when_perform_rejected(merchant_db):
    item = await order('payme')
    params = create_params(item)
    await rpc('CreateTransaction', params)
    async with get_db_connection() as db:
        await db.execute('UPDATE provider_transactions SET provider_time=?', (payments.now_ms() - payme.TIMEOUT,))
        await db.commit()
    assert (await rpc('PerformTransaction', {'id': params['id']}))['error']['code'] == -31008
    await init_db()
    tx = (await rpc('CheckTransaction', {'id': params['id']}))['result']
    assert tx['state'] == -1 and tx['reason'] == 4 and tx['cancel_time'] > 0
    assert (await payments.owned_order(item['id'], 111))['status'] == 'cancelled'


@pytest.mark.asyncio
async def test_payme_fiscal_sale_and_refund_records_are_separate(merchant_db):
    item = await order('payme')
    await rpc('CreateTransaction', create_params(item))
    for kind in ('PERFORM', 'CANCEL'):
        assert (await rpc('SetFiscalData', {'id': 'payme-1', 'type': kind, 'fiscal_data': {'receipt_id': kind}}))['result']['success']
    async with get_db_connection() as db:
        assert (await one(db, 'SELECT COUNT(*) n FROM payment_fiscal_data'))['n'] == 2


@pytest.mark.asyncio
async def test_browser_login_requires_nonce_approval_and_single_consumption(merchant_db):
    info, cookie = await browser_auth.create_login('ExampleBot')
    login_id = cookie.split('.')[0]
    assert info['code'] in (await browser_auth.pending(login_id))['code']
    assert await browser_auth.consume(cookie) is None
    with pytest.raises(PlatformError):
        await browser_auth.consume(login_id + '.forged')
    await browser_auth.approve(login_id, {'id': 111, 'first_name': 'Admin'})
    with pytest.raises(PlatformError):
        await browser_auth.approve(login_id, {'id': 222})
    results = await asyncio.gather(browser_auth.consume(cookie), browser_auth.consume(cookie), return_exceptions=True)
    assert sum(isinstance(r, dict) for r in results) == 1
    assert sum(isinstance(r, PlatformError) for r in results) == 1
    _, expired = await browser_auth.create_login('ExampleBot')
    async with get_db_connection() as db:
        await db.execute('UPDATE browser_logins SET expires_at=0')
        await db.commit()
    with pytest.raises(PlatformError):
        await browser_auth.consume(expired)


@pytest.mark.asyncio
async def test_web_api_browser_session_csrf_owner_and_return_query_cannot_settle(merchant_db, tmp_path, monkeypatch):
    # Python CI runs independently of the frontend build job. Keep this HTTP
    # security test independent of an ignored, locally built web/dist directory.
    frontend = tmp_path / 'frontend'
    frontend.mkdir()
    html = '<!doctype html><title>Payment return fixture</title>'
    (frontend / 'index.html').write_text(html, encoding='utf-8')
    monkeypatch.setattr(config, 'FRONTEND_PATH', str(frontend))
    app = create_web_app()
    app[BOT_USERNAME_KEY] = 'ExampleBot'
    async with TestClient(TestServer(app)) as client:
        assert (await client.get('/api/web-payments')).status == 401
        client.session.cookie_jar.update_cookies({'ayam_session': make_session({'id': 111})})
        assert (await client.get('/api/web-payments')).status == 403
        client.session.cookie_jar.update_cookies({'ayam_session': make_session({'id': 111}, audience='browser')})
        data = dict(provider='click', request_key=uuid.uuid4().hex, terms_version=payments.TERMS_VERSION, accepted_terms=True, amount=1, user_id=222)
        assert (await client.post('/api/web-payments/test', json=data, headers={'Origin': 'https://evil.example'})).status == 403
        response = await client.post('/api/web-payments/test', json=data, headers={'Origin': 'https://web.example'})
        assert response.status == 200
        item = await response.json()
        assert item['amount_uzs'] == 1000
        assert (await payments.owned_order(item['id'], 111))['user_id'] == 111
        returned = await client.get('/?payment=' + item['id'] + '&status=paid')
        assert returned.status == 200
        assert await returned.text() == html
        assert (await payments.owned_order(item['id'], 111))['status'] == 'created'
        client.session.cookie_jar.update_cookies({'ayam_session': make_session({'id': 222}, audience='browser')})
        assert (await client.get('/api/web-payments/orders/' + item['id'])).status == 404
        assert (await client.post('/api/web-payments/test', json=data)).status == 403


@pytest.mark.asyncio
async def test_callback_http_auth_without_browser_cookies_and_protocol_errors(merchant_db):
    item = await order()
    async with TestClient(TestServer(create_web_app())) as client:
        response = await client.post('/api/providers/click/test/prepare', data=click_data(item))
        assert response.status == 200 and (await response.json())['error'] == 0
        assert (await (await client.post('/api/providers/click/test/prepare', data='amount=1000&amount=1', headers={'Content-Type': 'application/x-www-form-urlencoded'})).json())['error'] == -8
        response = await client.post('/api/providers/payme/test', json={'method': 'GetStatement', 'params': {'from': 0, 'to': 1}})
        assert response.status == 200 and (await response.json())['error']['code'] == -32504
        response = await client.post('/api/providers/payme/test', data='{bad-json', headers={'Authorization': authorization()})
        assert response.status == 200 and (await response.json())['error']['code'] == -32700
        response = await client.post('/api/providers/payme/test', json={'id': 1, 'method': 'GetStatement', 'params': {'from': 0, 'to': 1}}, headers={'Authorization': authorization()})
        assert (await response.json())['result']['transactions'] == []
        async def chunks():
            yield b'{"id":42,"method":"Get'
            await asyncio.sleep(0.01)
            yield b'Statement","params":{"from":0,"to":1}}'
        response = await client.post('/api/providers/payme/test', data=chunks(), headers={'Authorization': authorization()})
        body = await response.json()
        assert body['id'] == 42 and body['result']['transactions'] == []


@pytest.mark.asyncio
async def test_telegram_entry_is_available_without_browser_checkout(merchant_db, monkeypatch):
    monkeypatch.setattr(config, 'BROWSER_APP_URL', '')
    app = create_web_app()
    app[BOT_USERNAME_KEY] = 'ExampleBot'
    async with TestClient(TestServer(app)) as client:
        assert await (await client.get('/api/browser-config')).json() == {
            'enabled': False, 'bot_url': 'https://t.me/ExampleBot?start=app',
        }
        assert (await client.get('/api/me')).status == 401


@pytest.mark.asyncio
async def test_browser_login_http_issues_browser_audience_cookie_only_after_approval(merchant_db):
    app = create_web_app()
    app[BOT_USERNAME_KEY] = 'ExampleBot'
    async with TestClient(TestServer(app)) as client:
        entry = await (await client.get('/api/browser-config')).json()
        assert entry['enabled'] and entry['bot_url'] == 'https://t.me/ExampleBot?start=app'
        response = await client.post('/api/browser-login')
        data = await response.json()
        assert response.cookies['browser_login']['httponly']
        login_id = data['bot_url'].split('web_')[1]
        cookie = response.cookies['browser_login'].value
        assert (await (await client.get('/api/browser-login', headers={'Cookie': 'browser_login=' + cookie})).json())['pending']
        await browser_auth.approve(login_id, {'id': 111, 'first_name': 'Admin'})
        # aiohttp's test server is HTTP; allow its secure fixture cookie explicitly.
        response = await client.get('/api/browser-login', headers={'Cookie': 'browser_login=' + cookie})
        assert not (await response.json())['pending']
        session = read_session_context(response.cookies['ayam_session'].value)
        assert session['audience'] == 'browser' and session['user']['id'] == 111
