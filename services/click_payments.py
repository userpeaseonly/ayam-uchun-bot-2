"""CLICK Shop API. Sign the original amount string; never use float money."""
import hashlib
import hmac
import re
from decimal import Decimal

from scripts.database.db import get_db_connection
from services import web_payments as payments
from services.platform_service import PlatformError


class ClickError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


async def process(environment, data, action):
    result = {key: data.get(key) for key in ('click_trans_id', 'merchant_trans_id')}
    try:
        env, merchant, secret, _ = payments.credentials('click', environment)
        required = ('click_trans_id', 'service_id', 'click_paydoc_id', 'merchant_trans_id',
                    'amount', 'action', 'error', 'sign_time', 'sign_string')
        if not all(isinstance(data.get(key), str) and 0 < len(data[key]) <= 128 for key in required):
            raise ClickError(-8, 'Invalid request')
        if data['action'] != str(action):
            raise ClickError(-3, 'Action not found')
        prepare = data.get('merchant_prepare_id', '') if action == 1 else ''
        if not re.fullmatch(r'[0-9]{1,20}', data['click_trans_id']) or (action == 1 and not re.fullmatch(r'[0-9]{1,10}', prepare)):
            raise ClickError(-8, 'Invalid transaction ID')
        signed = ''.join((data['click_trans_id'], data['service_id'], secret,
                          data['merchant_trans_id'], prepare, data['amount'], data['action'], data['sign_time']))
        signature = hashlib.md5(signed.encode(), usedforsecurity=False).hexdigest()
        if (data['service_id'] != merchant or not re.fullmatch('[a-fA-F0-9]{32}', data['sign_string'])
                or not hmac.compare_digest(signature, data['sign_string'].lower())):
            raise ClickError(-1, 'Signature check failed')
        if not re.fullmatch(r'[0-9]{1,12}(\.[0-9]{1,2})?', data['amount']):
            raise ClickError(-2, 'Incorrect amount')
        if not re.fullmatch(r'-?[0-9]{1,8}', data['error']):
            raise ClickError(-8, 'Invalid error code')
        if int(data['error']) > 0:
            raise ClickError(-8, 'Unknown payment status')
        amount = int(Decimal(data['amount']) * 100)
        async with get_db_connection(timeout=3) as db:
            await db.execute('BEGIN IMMEDIATE')
            try:
                order = await payments.callback_order(db, 'click', env, merchant, data['merchant_trans_id'])
                if not order:
                    raise ClickError(-5, 'Order not found')
                if amount != order['amount']:
                    raise ClickError(-2, 'Incorrect amount')
                tx = await payments.transaction(db, 'click', env, merchant, data['click_trans_id'])
                if tx and tx['order_id'] != order['id']:
                    raise ClickError(-6, 'Transaction mismatch')
                if action == 1 and (not tx or str(tx['id']) != prepare):
                    raise ClickError(-6, 'Transaction not found')
                if order['status'] == 'paid':
                    raise ClickError(-4, 'Already paid')
                if order['status'] in ('cancelled', 'refunded'):
                    raise ClickError(-9, 'Transaction cancelled')
                if not tx:
                    if order['status'] != 'created' or order['expires_at'] <= payments.now_ms():
                        raise ClickError(-9, 'Order expired or reserved')
                    if int(data['error']) < 0:
                        raise ClickError(-9, 'Transaction cancelled')
                    tx = await payments.insert_transaction(db, order, data['click_trans_id'], payments.now_ms())
                if tx['state'] < 0:
                    raise ClickError(-9, 'Transaction cancelled')
                if int(data['error']) < 0:
                    await payments.change_state(db, tx, -1, int(data['error']))
                    raise ClickError(-9, 'Transaction cancelled')
                if action == 1:
                    await payments.change_state(db, tx, 2)
                result['merchant_confirm_id' if action else 'merchant_prepare_id'] = tx['id']
                result.update(error=0, error_note='Success')
            except ClickError as error:
                result.update(error=error.code, error_note=error.message)
            await db.commit()
    except ClickError as error:
        result.update(error=error.code, error_note=error.message)
    except PlatformError:
        result.update(error=-8, error_note='Merchant not configured')
    return result
