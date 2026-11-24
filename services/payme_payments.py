"""Payme Merchant API: durable, scoped, serialized financial transitions."""
import base64
import hmac
import json

from scripts.database.db import get_db_connection
from services import web_payments as payments
from services.platform_service import PlatformError, one, rows
from services.stars_payments import scope

TIMEOUT = 43200000


class RpcError(Exception):
    def __init__(self, code, message, data=None):
        self.code, self.message, self.data = code, message, data


def error_response(request_id, code, message, data=None):
    return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': code,
            'message': {language: message for language in ('uz', 'ru', 'en')}, 'data': data}}


def authorize(environment, authorization):
    try:
        env, merchant, secret, _ = payments.credentials('payme', environment)
    except PlatformError:
        raise RpcError(-32504, 'Merchant not configured') from None
    expected = base64.b64encode(('Paycom:' + secret).encode()).decode()
    if (not isinstance(authorization, str) or not authorization.lower().startswith('basic ')
            or not hmac.compare_digest(authorization[6:].encode(), expected.encode())):
        raise RpcError(-32504, 'Authorization failed')
    return env, merchant


def integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        raise RpcError(-32600, 'Invalid integer parameter')
    return value


def tx_result(tx):
    return {key: tx[key] for key in ('create_time', 'perform_time', 'cancel_time', 'state', 'reason')} | {'transaction': str(tx['id'])}


async def expire(db, tx):
    if tx and tx['state'] == 1 and payments.now_ms() - tx['provider_time'] >= TIMEOUT:
        await payments.change_state(db, tx, -1, 4)
        tx = await one(db, 'SELECT * FROM provider_transactions WHERE id=?', (tx['id'],))
    return tx


async def dispatch(db, env, merchant, method, params):
    if method == 'GetStatement':
        start, end = integer(params.get('from')), integer(params.get('to'))
        if end < start:
            raise RpcError(-32600, 'Invalid period')
        records = await rows(db, '''SELECT t.*,o.amount FROM provider_transactions t JOIN web_payment_orders o ON o.id=t.order_id
            WHERE t.provider='payme' AND t.environment=? AND t.bot_id=? AND t.merchant=?
            AND t.provider_time BETWEEN ? AND ? ORDER BY t.provider_time,t.id''', (env, scope()[0], merchant, start, end))
        return {'transactions': [tx_result(t) | {'id': t['external_id'], 'time': t['provider_time'],
                'amount': t['amount'], 'account': {'order_id': t['order_id']}} for t in records]}
    if method in ('CheckPerformTransaction', 'CreateTransaction'):
        account = params.get('account')
        if not isinstance(account, dict) or not isinstance(account.get('order_id'), str):
            raise RpcError(-31050, 'Order not found', 'order_id')
        order = await payments.callback_order(db, 'payme', env, merchant, account['order_id'])
        if not order:
            raise RpcError(-31050, 'Order not found', 'order_id')
        if type(params.get('amount')) is not int or params['amount'] != order['amount']:
            raise RpcError(-31001, 'Incorrect amount')
        if method == 'CreateTransaction':
            external_id = params.get('id')
            if not isinstance(external_id, str) or not 1 <= len(external_id) <= 128:
                raise RpcError(-32600, 'Invalid transaction ID')
            provider_time = integer(params.get('time'), 1)
            tx = await expire(db, await payments.transaction(db, 'payme', env, merchant, external_id))
            if tx:
                if tx['order_id'] != order['id'] or tx['provider_time'] != provider_time or tx['state'] < 0:
                    raise RpcError(-31008, 'Transaction cannot be created')
                return {key: tx_result(tx)[key] for key in ('create_time', 'transaction', 'state')}
            if provider_time > payments.now_ms() + 60000 or payments.now_ms() - provider_time >= TIMEOUT:
                raise RpcError(-31008, 'Transaction time invalid')
        if order['status'] != 'created' or order['expires_at'] <= payments.now_ms():
            raise RpcError(-31008, 'Order closed or reserved')
        if method == 'CheckPerformTransaction':
            return {'allow': True}
        tx = await payments.insert_transaction(db, order, external_id, provider_time)
        return {key: tx_result(tx)[key] for key in ('create_time', 'transaction', 'state')}
    if method not in ('PerformTransaction', 'CancelTransaction', 'CheckTransaction', 'SetFiscalData'):
        raise RpcError(-32601, 'Method not found', method)
    if not isinstance(params.get('id'), str) or not 1 <= len(params['id']) <= 128:
        raise RpcError(-32600, 'Invalid transaction ID')
    tx = await expire(db, await payments.transaction(db, 'payme', env, merchant, params['id']))
    if not tx:
        raise RpcError(-31003, 'Transaction not found')
    if method == 'SetFiscalData':
        kind, data = params.get('type'), params.get('fiscal_data')
        if kind not in ('PERFORM', 'CANCEL') or not isinstance(data, dict) or len(json.dumps(data)) > 16000:
            raise RpcError(-32602, 'Invalid fiscal data')
        await db.execute('''INSERT INTO payment_fiscal_data(transaction_id,kind,data_json) VALUES (?,?,?)
            ON CONFLICT(transaction_id,kind) DO UPDATE SET data_json=excluded.data_json''', (tx['id'], kind, json.dumps(data)))
        return {'success': True}
    if method == 'PerformTransaction':
        if tx['state'] < 0:
            raise RpcError(-31008, 'Transaction cancelled')
        if tx['state'] == 1:
            await payments.change_state(db, tx, 2)
    elif method == 'CancelTransaction':
        reason = integer(params.get('reason'), 1)
        if reason not in (1, 2, 3, 4, 5, 10):
            raise RpcError(-32600, 'Invalid cancellation reason')
        if tx['state'] > 0:
            await payments.change_state(db, tx, -2 if tx['state'] == 2 else -1, reason)
    tx = await one(db, 'SELECT * FROM provider_transactions WHERE id=?', (tx['id'],))
    result = tx_result(tx)
    if method == 'PerformTransaction':
        return {key: result[key] for key in ('transaction', 'perform_time', 'state')}
    if method == 'CancelTransaction':
        return {key: result[key] for key in ('transaction', 'cancel_time', 'state')}
    return result


async def process(environment, authorization, data):
    request_id = data.get('id') if isinstance(data, dict) else None
    try:
        env, merchant = authorize(environment, authorization)
        if (not isinstance(data, dict) or not isinstance(data.get('method'), str)
                or not isinstance(data.get('params'), dict)
                or (request_id is not None and type(request_id) not in (str, int))):
            raise RpcError(-32600, 'Invalid RPC request')
        async with get_db_connection(timeout=3) as db:
            await db.execute('BEGIN IMMEDIATE')
            try:
                result = await dispatch(db, env, merchant, data['method'], data['params'])
                response = {'jsonrpc': '2.0', 'id': request_id, 'result': result}
            except RpcError as error:
                response = error_response(request_id, error.code, error.message, error.data)
            # Timeout cancellation must persist even when the operation is rejected.
            await db.commit()
        return response
    except RpcError as error:
        return error_response(request_id, error.code, error.message, error.data)
