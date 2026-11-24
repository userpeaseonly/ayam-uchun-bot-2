"""Direct merchant checkout for the standalone website. No assessment grants."""
import base64
import re
import time
import uuid
from urllib.parse import urlencode, urlsplit

import config
from scripts.database.db import get_db_connection
from services.platform_service import PlatformError, one, rows
from services.stars_payments import scope, support_url

TERMS_VERSION = 'web-payment-pilot-v1'
TERMS_TEXT = ('Bu 1 000 so‘mlik to‘lov integratsiyasi sinovi. Test, obuna yoki balans berilmaydi. '
              'Payme sandboxida haqiqiy pul sarflanmaydi. Click uchun alohida test xizmati kerak. '
              'Jonli muhitda haqiqiy pul yechiladi. Qaytarish va yordam uchun buyurtma raqami bilan '
              'yordam xizmatiga murojaat qiling. Testlarga kirish hozir bepul.')
AMOUNT = 100000  # Integer tiyin internally; Click receives UZS, Payme receives tiyin.
TTL = 15 * 60 * 1000


def now_ms():
    return int(time.time() * 1000)


def browser_url():
    url = config.BROWSER_APP_URL
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost'))
            or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('', '/')):
        raise PlatformError('Brauzer ilovasi manzili sozlanmagan.', 503)
    return url.rstrip('/')


def credentials(provider, environment=None):
    if provider not in ('click', 'payme'):
        raise PlatformError('To‘lov usuli noto‘g‘ri.')
    environment = environment or getattr(config, provider.upper() + '_ENVIRONMENT')
    if environment not in ('test', 'live'):
        raise PlatformError('To‘lov muhiti noto‘g‘ri.', 503)
    prefix = provider.upper() + ('_TEST' if environment == 'test' else '')
    merchant = getattr(config, prefix + ('_SERVICE_ID' if provider == 'click' else '_MERCHANT_ID'))
    secret = getattr(config, prefix + ('_SECRET_KEY' if provider == 'click' else '_KEY'))
    extra = getattr(config, prefix + '_MERCHANT_ID') if provider == 'click' else merchant
    valid_id = r'[1-9][0-9]{0,15}' if provider == 'click' else r'[A-Za-z0-9_-]{1,80}'
    if not re.fullmatch(valid_id, merchant) or not re.fullmatch(valid_id, extra) or not secret or secret.startswith('your_'):
        raise PlatformError('Provayderning merchant sozlamalari hali kiritilmagan.', 503)
    return environment, merchant, secret, extra


def available(provider, user_id):
    try:
        env, *_ = credentials(provider)
        browser_url()
        return bool(config.WEB_TEST_PAYMENTS_ENABLED and user_id in config.ADMIN_IDS and support_url()
                    and (env == 'test' or config.WEB_ALLOW_LIVE_TEST_PAYMENTS))
    except PlatformError:
        return False


def settings(user_id):
    return {'providers': [{'id': p, 'enabled': available(p, user_id),
                          'environment': getattr(config, p.upper() + '_ENVIRONMENT')} for p in ('click', 'payme')],
            'amount_uzs': AMOUNT // 100, 'terms_version': TERMS_VERSION,
            'terms_text': TERMS_TEXT, 'support_url': support_url()}


def public_order(order, *, checkout=False):
    data = {key: order[key] for key in ('id', 'provider', 'environment', 'status', 'created_at', 'expires_at')}
    data['amount_uzs'] = order['amount'] // 100
    if order['status'] == 'created' and order['expires_at'] <= now_ms():
        data['status'] = 'expired'
    if checkout and data['status'] == 'created' and available(order['provider'], order['user_id']):
        env, merchant, _, extra = credentials(order['provider'])
        if (env, merchant) != (order['environment'], order['merchant']):
            return data
        return_url = browser_url() + '/?payment=' + order['id']
        if order['provider'] == 'click':
            data['checkout_url'] = 'https://my.click.uz/services/pay?' + urlencode({
                'service_id': merchant, 'merchant_id': extra, 'transaction_param': order['id'],
                'amount': f"{order['amount'] // 100}.{order['amount'] % 100:02d}", 'return_url': return_url})
        else:
            params = f"m={merchant};ac.order_id={order['id']};a={order['amount']};l=uz;c={return_url}"
            host = 'https://test.paycom.uz/' if env == 'test' else 'https://checkout.paycom.uz/'
            data['checkout_url'] = host + base64.b64encode(params.encode()).decode()
    return data


async def owned_order(order_id, user_id):
    async with get_db_connection() as db:
        item = await one(db, 'SELECT * FROM web_payment_orders WHERE id=? AND user_id=? AND bot_id=?', (order_id, user_id, scope()[0]))
    if not item:
        raise PlatformError('Buyurtma topilmadi.', 404)
    return item


async def history(user_id):
    async with get_db_connection() as db:
        orders = await rows(db, 'SELECT * FROM web_payment_orders WHERE user_id=? AND bot_id=? ORDER BY created_at DESC LIMIT 30', (user_id, scope()[0]))
    return {'settings': settings(user_id), 'orders': [public_order(o, checkout=True) for o in orders]}


async def visible(user_id):
    if any(available(provider, user_id) for provider in ('click', 'payme')):
        return True
    async with get_db_connection() as db:
        return bool(await one(db, 'SELECT id FROM web_payment_orders WHERE user_id=? AND bot_id=? LIMIT 1', (user_id, scope()[0])))


async def create_order(user_id, provider, request_key, terms_version, accepted):
    if not available(provider, user_id):
        raise PlatformError('Bu sinov to‘lovi hozir yoqilmagan.', 403)
    if not isinstance(request_key, str) or not re.fullmatch('[a-f0-9]{32}', request_key):
        raise PlatformError('So‘rov raqami noto‘g‘ri.')
    if accepted is not True or terms_version != TERMS_VERSION:
        raise PlatformError('Joriy sinov shartlarini tasdiqlang.')
    env, merchant, *_ = credentials(provider)
    bot_id = scope()[0]
    current = now_ms()
    async with get_db_connection() as db:
        await db.execute('BEGIN IMMEDIATE')
        item = await one(db, '''SELECT * FROM web_payment_orders WHERE user_id=? AND bot_id=?
            AND provider=? AND environment=? AND merchant=? AND request_key=?''', (user_id, bot_id, provider, env, merchant, request_key))
        if not item:
            order_id = uuid.uuid4().hex
            await db.execute('''INSERT INTO web_payment_orders
                (id,user_id,bot_id,provider,environment,merchant,request_key,purpose,amount,terms_version,accepted_at,created_at,expires_at)
                VALUES (?,?,?,?,?,?,?,'integration_test',?,?,?,?,?)''',
                (order_id, user_id, bot_id, provider, env, merchant, request_key, AMOUNT, TERMS_VERSION, current, current, current + TTL))
            item = await one(db, 'SELECT * FROM web_payment_orders WHERE id=?', (order_id,))
        await db.commit()
    return public_order(item, checkout=True)


async def callback_order(db, provider, env, merchant, order_id):
    return await one(db, '''SELECT * FROM web_payment_orders WHERE id=? AND bot_id=?
        AND provider=? AND environment=? AND merchant=?''', (order_id, scope()[0], provider, env, merchant))


async def transaction(db, provider, env, merchant, external_id):
    return await one(db, '''SELECT * FROM provider_transactions WHERE provider=? AND environment=?
        AND bot_id=? AND merchant=? AND external_id=?''', (provider, env, scope()[0], merchant, external_id))


async def change_state(db, tx, state, reason=None):
    timestamp = now_ms()
    await db.execute('''UPDATE provider_transactions SET state=?,reason=?,perform_time=?,cancel_time=? WHERE id=?''',
                     (state, reason, timestamp if state == 2 else tx['perform_time'], timestamp if state < 0 else tx['cancel_time'], tx['id']))
    await db.execute('UPDATE web_payment_orders SET status=? WHERE id=?',
                     ({1: 'pending', 2: 'paid', -1: 'cancelled', -2: 'refunded'}[state], tx['order_id']))


async def insert_transaction(db, order, external_id, provider_time):
    await db.execute('''INSERT INTO provider_transactions
        (order_id,provider,environment,bot_id,merchant,external_id,provider_time,create_time,state)
        VALUES (?,?,?,?,?,?,?,?,1)''', (order['id'], order['provider'], order['environment'], order['bot_id'], order['merchant'], external_id, provider_time, now_ms()))
    await db.execute("UPDATE web_payment_orders SET status='pending' WHERE id=?", (order['id'],))
    return await transaction(db, order['provider'], order['environment'], order['merchant'], external_id)
