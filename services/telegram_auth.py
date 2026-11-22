"""Telegram initData verification and short-lived, signed HttpOnly sessions."""

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

import config
from services.platform_service import PlatformError


def verify_init_data(raw, *, now=None):
    try:
        if not isinstance(raw, str) or len(raw) > 16000 or not config.BOT_TOKEN:
            raise ValueError()
        pairs = parse_qsl(raw, strict_parsing=True)
        data = dict(pairs)
        if len(data) != len(pairs):
            raise ValueError()
        received = data.pop("hash")
        secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
        check = "\n".join(f"{key}={data[key]}" for key in sorted(data))
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(received, expected):
            raise ValueError()
        age = (time.time() if now is None else now) - int(data["auth_date"])
        if age < -30 or age > config.TELEGRAM_AUTH_MAX_AGE:
            raise ValueError()
        user = json.loads(data["user"])
        if type(user["id"]) is not int or user["id"] <= 0:
            raise ValueError()
        return {key: user[key] for key in ("id", "first_name", "last_name", "username") if key in user}
    except (ValueError, KeyError, TypeError) as error:
        raise PlatformError("Telegram sessiyasi yaroqsiz. Mini App'ni botdan qayta oching.", 401) from error


def session_signature(payload):
    secret = hmac.new(config.BOT_TOKEN.encode(), b"mini-app-session-v1", hashlib.sha256).digest()
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def make_session(user):
    payload = base64.urlsafe_b64encode(json.dumps({"user": user, "exp": int(time.time()) + 12 * 3600}, separators=(",", ":")).encode()).decode()
    return payload + "." + session_signature(payload)


def read_session(token):
    try:
        payload, signature = token.rsplit(".", 1)
        if len(token) > 8000 or not config.BOT_TOKEN or not hmac.compare_digest(signature, session_signature(payload)):
            raise ValueError()
        value = json.loads(base64.urlsafe_b64decode(payload))
        if value["exp"] <= time.time():
            raise ValueError()
        return value["user"]
    except (ValueError, KeyError, TypeError) as error:
        raise PlatformError("Sessiya tugagan. Mini App'ni qayta oching.", 401) from error
