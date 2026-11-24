"""Browser-held nonce plus explicit approval in the user's private bot chat."""
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid

from scripts.database.db import get_db_connection
from services.platform_service import PlatformError, one
from services.web_payments import browser_url


async def create_login(username):
    browser_url()
    if not username or not re.fullmatch(r'[A-Za-z0-9_]{5,32}', username):
        raise PlatformError('Brauzerga kirish hali sozlanmagan.', 503)
    login_id, nonce = uuid.uuid4().hex, secrets.token_urlsafe(32)
    code = f'{secrets.randbelow(1000000):06d}'
    async with get_db_connection() as db:
        await db.execute('BEGIN IMMEDIATE')
        await db.execute('DELETE FROM browser_logins WHERE expires_at<?', (time.time(),))
        if (await one(db, 'SELECT COUNT(*) n FROM browser_logins'))['n'] >= 500:
            raise PlatformError('Keyinroq qayta urinib ko‘ring.', 429)
        await db.execute('INSERT INTO browser_logins(id,poll_hash,expires_at,code) VALUES (?,?,?,?)',
                         (login_id, hashlib.sha256(nonce.encode()).hexdigest(), time.time() + 300, code))
        await db.commit()
    return {'code': code, 'bot_url': f'https://t.me/{username}?start=web_{login_id}'}, login_id + '.' + nonce


async def pending(login_id):
    if not re.fullmatch('[a-f0-9]{32}', login_id):
        raise PlatformError('Kirish so‘rovi noto‘g‘ri.')
    async with get_db_connection() as db:
        item = await one(db, 'SELECT * FROM browser_logins WHERE id=?', (login_id,))
    if not item or item['consumed'] or item['expires_at'] <= time.time():
        raise PlatformError('Kirish so‘rovi tugagan. Brauzerda qayta boshlang.', 410)
    return item


async def approve(login_id, identity):
    browser_url()
    await pending(login_id)
    identity = {key: identity[key] for key in ('id', 'first_name', 'last_name', 'username') if key in identity}
    async with get_db_connection() as db:
        await db.execute('BEGIN IMMEDIATE')
        item = await one(db, 'SELECT * FROM browser_logins WHERE id=?', (login_id,))
        if not item or item['consumed'] or item['expires_at'] <= time.time():
            raise PlatformError('Kirish so‘rovi tugagan.', 410)
        if item['identity_json'] and json.loads(item['identity_json'])['id'] != identity['id']:
            raise PlatformError('So‘rov boshqa hisob tomonidan tasdiqlangan.', 409)
        await db.execute('UPDATE browser_logins SET identity_json=? WHERE id=?', (json.dumps(identity), login_id))
        await db.commit()


async def consume(cookie):
    browser_url()
    try:
        login_id, nonce = cookie.split('.', 1)
        if len(cookie) > 128:
            raise ValueError()
    except (ValueError, AttributeError):
        raise PlatformError('Kirishni brauzerda qayta boshlang.', 401) from None
    async with get_db_connection() as db:
        await db.execute('BEGIN IMMEDIATE')
        item = await one(db, 'SELECT * FROM browser_logins WHERE id=?', (login_id,))
        if (not item or not hmac.compare_digest(hashlib.sha256(nonce.encode()).hexdigest(), item['poll_hash'])
                or item['expires_at'] <= time.time() or item['consumed']):
            raise PlatformError('Kirish so‘rovi tugagan yoki yaroqsiz.', 410)
        if not item['identity_json']:
            return None
        await db.execute('UPDATE browser_logins SET consumed=1 WHERE id=?', (login_id,))
        await db.commit()
        return json.loads(item['identity_json'])
