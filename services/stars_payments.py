"""Native Stars integration testing; no assessment access or wallet grants.

Only trusted Bot API updates / transaction history can settle payments. Browser
checkout callbacks are advisory. Orders and receipts are scoped to a bot and to
Telegram's genuinely separate test/live environments.
"""

import asyncio
import logging
import re
import time
import uuid
from urllib.parse import urlsplit
from weakref import WeakValueDictionary

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import LabeledPrice

import config
from scripts.database.db import get_db_connection
from services.platform_service import PlatformError, one, rows

logger = logging.getLogger(__name__)
TERMS_VERSION = "stars-integration-test-v1"
TERMS_TEXT = (
    "Bu faqat Telegram Stars to‘lov integratsiyasini tekshirish uchun 1 Starslik sinov. "
    "Test serverida haqiqiy Stars sarflanmaydi. Jonli muhitda haqiqiy 1 Stars yechiladi. "
    "Sinov hech qanday test, obuna, balans yoki kirish huquqini bermaydi. "
    "To‘lov tarixidan Starsni to‘liq qaytarishni so‘rashingiz mumkin. "
    "Muammo bo‘lsa /paysupport orqali ko‘rsatilgan yordam manziliga buyurtma raqamini yuboring. "
    "To‘lovlar bo‘yicha yordamni platforma ko‘rsatadi; Telegram yordam xizmati emas."
)
PREFIX = "stars-test:"
AMOUNT = 1
ORDER_TTL = 15 * 60
invoice_locks = WeakValueDictionary()


def scope():
    try:
        bot_id = int(config.BOT_TOKEN.split(":", 1)[0])
    except (ValueError, AttributeError):
        raise PlatformError("Bot sozlanmagan.", 503)
    return bot_id, "test" if config.TELEGRAM_TEST_ENVIRONMENT else "live"


def support_url():
    username = config.PAYMENT_SUPPORT_USERNAME.lstrip("@")
    return "https://t.me/" + username if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", username) else None


def enabled(user_id):
    return (user_id in config.ADMIN_IDS and config.STARS_TEST_PAYMENTS_ENABLED
            and bool(support_url())
            and (config.TELEGRAM_TEST_ENVIRONMENT or config.STARS_ALLOW_LIVE_TEST_PAYMENTS))


def settings(user_id):
    return {"enabled": bool(enabled(user_id)), "environment": scope()[1], "amount": AMOUNT,
            "currency": "XTR", "terms_version": TERMS_VERSION, "terms_text": TERMS_TEXT,
            "support_url": support_url()}


async def visible(user_id):
    if enabled(user_id):
        return True
    bot_id, environment = scope()
    async with get_db_connection() as db:
        return bool(await one(db, "SELECT id FROM payment_orders WHERE user_id=? AND bot_id=? AND environment=? LIMIT 1", (user_id, bot_id, environment))
                    or await one(db, "SELECT charge_id FROM star_receipts WHERE user_id=? AND bot_id=? AND environment=? LIMIT 1", (user_id, bot_id, environment)))


def public_order(order):
    status = order["status"]
    if status in ("created", "invoice_ready", "checkout", "invoice_failed") and order["expires_at"] <= time.time():
        status = "expired"
    return {key: order[key] for key in ("id", "amount", "currency", "purpose", "environment", "created_at", "expires_at", "invoice_url")} | {"status": status}


async def owned_order(order_id, user_id):
    bot_id, environment = scope()
    async with get_db_connection() as db:
        order = await one(db, "SELECT * FROM payment_orders WHERE id=? AND user_id=? AND bot_id=? AND environment=?", (order_id, user_id, bot_id, environment))
    if not order:
        raise PlatformError("To‘lov buyurtmasi topilmadi.", 404)
    return order


async def history(user_id):
    bot_id, environment = scope()
    async with get_db_connection() as db:
        orders = await rows(db, "SELECT * FROM payment_orders WHERE user_id=? AND bot_id=? AND environment=? ORDER BY created_at DESC LIMIT 30", (user_id, bot_id, environment))
        extra = await rows(db, "SELECT amount, status, received_at FROM star_receipts WHERE user_id=? AND bot_id=? AND environment=? AND (order_id IS NULL OR issue IS NOT NULL) ORDER BY received_at DESC LIMIT 30", (user_id, bot_id, environment))
    return {"settings": settings(user_id), "orders": [public_order(order) for order in orders], "additional_payments": extra}


async def create_test_order(user_id, request_key, terms_version, accepted, bot):
    if not enabled(user_id):
        raise PlatformError("Stars sinov to‘lovlari yoqilmagan yoki sizga ruxsat berilmagan.", 403)
    if not isinstance(request_key, str) or not re.fullmatch(r"[a-f0-9]{32}", request_key):
        raise PlatformError("Buyurtma so‘rovi noto‘g‘ri.")
    if accepted is not True or terms_version != TERMS_VERSION:
        raise PlatformError("Joriy sinov shartlarini o‘qib, tasdiqlang.")
    bot_id, environment = scope()
    now = time.time()
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        order = await one(db, "SELECT * FROM payment_orders WHERE user_id=? AND bot_id=? AND environment=? AND request_key=?", (user_id, bot_id, environment, request_key))
        if not order:
            order_id = uuid.uuid4().hex
            await db.execute("""INSERT INTO payment_orders
                (id,user_id,bot_id,environment,request_key,purpose,amount,currency,terms_version,accepted_at,created_at,expires_at)
                VALUES (?,?,?,?,?,'stars_integration_test',?,'XTR',?,?,?,?)""",
                (order_id, user_id, bot_id, environment, request_key, AMOUNT, TERMS_VERSION, now, now, now + ORDER_TTL))
            order = await one(db, "SELECT * FROM payment_orders WHERE id=?", (order_id,))
        await db.commit()
    # Never hold a SQLite write transaction across a Bot API request.
    lock = invoice_locks.get(order["id"])
    if lock is None:
        lock = asyncio.Lock()
        invoice_locks[order["id"]] = lock
    async with lock:
        order = await owned_order(order["id"], user_id)
        if order["invoice_url"] or public_order(order)["status"] == "expired" or order["status"] not in ("created", "invoice_failed"):
            return public_order(order)
        try:
            url = await bot.create_invoice_link(title="Basirat · Stars sinovi", description="1 Starslik integratsiya sinovi. Hech qanday test yoki xizmat ochilmaydi. Starsni tarixdan qaytarish mumkin.",
                payload=PREFIX + order["id"], currency="XTR", provider_token="",
                prices=[LabeledPrice(label="Sinov to‘lovi", amount=AMOUNT)], request_timeout=8)
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.netloc != "t.me" or not parsed.path.startswith("/$"):
                raise ValueError("Unexpected invoice URL")
        except Exception as error:
            async with get_db_connection() as db:
                await db.execute("UPDATE payment_orders SET status='invoice_failed' WHERE id=? AND status='created'", (order["id"],))
                await db.commit()
            logger.warning("Stars invoice creation failed: %s", type(error).__name__)
            raise PlatformError("Telegram hisobini yaratib bo‘lmadi. Shu so‘rovni qayta urinib ko‘ring.", 503) from None
        async with get_db_connection() as db:
            await db.execute("UPDATE payment_orders SET invoice_url=?,status='invoice_ready' WHERE id=? AND status IN ('created','invoice_failed')", (url, order["id"]))
            await db.commit()
        return public_order(await owned_order(order["id"], user_id))


def order_id_from(payload):
    if isinstance(payload, str) and re.fullmatch(PREFIX + r"[a-f0-9]{32}", payload):
        return payload[len(PREFIX):]
    return None


async def validate_checkout(user_id, payload, currency, amount, query_id):
    if not enabled(user_id):
        raise PlatformError("Sinov to‘lovi hozir qabul qilinmaydi.")
    order_id = order_id_from(payload)
    bot_id, environment = scope()
    # Apply the short lock wait during connection setup as well, so a cancelled
    # aiosqlite operation cannot keep checkout waiting on the default 60s lock.
    async with get_db_connection(timeout=1.5) as db:
        await db.execute("BEGIN IMMEDIATE")
        order = await one(db, "SELECT * FROM payment_orders WHERE id=? AND user_id=? AND bot_id=? AND environment=?", (order_id, user_id, bot_id, environment))
        if not order or currency != "XTR" or type(amount) is not int or amount != order["amount"]:
            raise PlatformError("To‘lov ma’lumotlari buyurtmaga mos emas.")
        if order["expires_at"] <= time.time() or order["status"] not in ("invoice_ready", "checkout"):
            raise PlatformError("Buyurtma yopilgan yoki muddati tugagan. Yangi buyurtma oching.")
        if order["pre_checkout_id"] and order["pre_checkout_id"] != query_id:
            raise PlatformError("Bu buyurtma uchun to‘lov allaqachon tasdiqlanmoqda. Tarixni tekshiring.")
        await db.execute("UPDATE payment_orders SET status='checkout',pre_checkout_id=? WHERE id=?", (query_id, order_id))
        await db.commit()


async def record_payment(user_id, payload, currency, amount, charge_id, *, refunded=False):
    """Durably record a trusted update, even after checkout expires / is disabled.

    Extra or mismatched charges are recorded and automatically queued for refund.
    Refund-before-success delivery never regresses a receipt back to 'paid'.
    """
    if currency != "XTR" or type(amount) is not int or amount < 1:
        raise PlatformError("Stars to‘lovi noto‘g‘ri.")
    if not isinstance(charge_id, str) or not 1 <= len(charge_id) <= 512:
        raise PlatformError("To‘lov raqami noto‘g‘ri.")
    if not isinstance(payload, str) or not 1 <= len(payload.encode('utf-8')) <= 128:
        raise PlatformError("To‘lov ma’lumotlari noto‘g‘ri.")
    bot_id, environment = scope()
    order_id = order_id_from(payload)
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        order = await one(db, "SELECT * FROM payment_orders WHERE id=? AND bot_id=? AND environment=?", (order_id, bot_id, environment))
        valid = bool(order and order["user_id"] == user_id and order["amount"] == amount)
        receipt = await one(db, "SELECT * FROM star_receipts WHERE charge_id=? AND bot_id=? AND environment=?", (charge_id, bot_id, environment))
        if receipt and (receipt["user_id"] != user_id or receipt["amount"] != amount or receipt["payload"] != payload):
            raise PlatformError("Takroriy to‘lov ma’lumotlari mos emas.")
        issue = None if valid else "order_mismatch"
        if valid and order["charge_id"] and order["charge_id"] != charge_id:
            issue = "extra_payment"
        if not receipt:
            await db.execute("""INSERT INTO star_receipts
                (charge_id,bot_id,environment,order_id,user_id,payload,amount,status,issue,received_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (charge_id, bot_id, environment, order["id"] if valid else None, user_id, payload, amount,
                 "refunded" if refunded else "refund_pending" if issue else "paid", issue, time.time()))
        elif refunded:
            await db.execute("UPDATE star_receipts SET status='refunded' WHERE charge_id=? AND bot_id=? AND environment=?", (charge_id, bot_id, environment))
        if refunded:
            await db.execute("UPDATE star_receipts SET refunded_at=COALESCE(refunded_at,?) WHERE charge_id=? AND bot_id=? AND environment=?", (time.time(), charge_id, bot_id, environment))
        receipt = await one(db, "SELECT * FROM star_receipts WHERE charge_id=? AND bot_id=? AND environment=?", (charge_id, bot_id, environment))
        if valid and (not order["charge_id"] or order["charge_id"] == charge_id):
            await db.execute("UPDATE payment_orders SET charge_id=?,status=? WHERE id=?", (charge_id, receipt["status"], order["id"]))
        await db.commit()
    return {"order_id": order["id"] if valid else None, "status": receipt["status"]}


async def request_refund(order_id, user_id):
    # Previously paid users retain refunds/history after disabling new purchases.
    order = await owned_order(order_id, user_id)
    if order["status"] == "refunded":
        return public_order(order)
    if not order["charge_id"]:
        raise PlatformError("Bu buyurtma uchun tasdiqlangan to‘lov yo‘q.", 409)
    bot_id, environment = scope()
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        await db.execute("UPDATE star_receipts SET status='refund_pending',next_refund_at=0 WHERE charge_id=? AND bot_id=? AND environment=? AND status!='refunded'", (order["charge_id"], bot_id, environment))
        receipt = await one(db, "SELECT status FROM star_receipts WHERE charge_id=? AND bot_id=? AND environment=?", (order["charge_id"], bot_id, environment))
        await db.execute("UPDATE payment_orders SET status=? WHERE id=?", (receipt["status"], order_id))
        await db.commit()
    return public_order(await owned_order(order_id, user_id))


async def refund_pending(bot):
    bot_id, environment = scope()
    async with get_db_connection() as db:
        pending = await rows(db, "SELECT * FROM star_receipts WHERE bot_id=? AND environment=? AND status='refund_pending' AND next_refund_at<=? ORDER BY received_at LIMIT 10", (bot_id, environment, time.time()))
    for receipt in pending:
        try:
            try:
                result = await bot.refund_star_payment(user_id=receipt["user_id"], telegram_payment_charge_id=receipt["charge_id"], request_timeout=8)
                if result is not True:
                    raise RuntimeError("Refund not confirmed")
            except TelegramBadRequest as error:
                if "CHARGE_ALREADY_REFUNDED" not in error.message:
                    raise
            await record_payment(receipt["user_id"], receipt["payload"], "XTR", receipt["amount"], receipt["charge_id"], refunded=True)
        except Exception as error:
            logger.warning("Stars refund pending: %s", type(error).__name__)
            async with get_db_connection() as db:
                await db.execute("UPDATE star_receipts SET refund_attempts=refund_attempts+1,next_refund_at=? WHERE charge_id=? AND bot_id=? AND environment=? AND status='refund_pending'", (time.time() + min(300, 5 * 2 ** min(receipt["refund_attempts"], 6)), receipt["charge_id"], bot_id, environment))
                await db.commit()


async def reconcile(bot):
    """Small private pilot: scan the bot's history, including delayed refunds.

    No positional watermark: a late transaction or same-ID refund must not be
    missed. Only this integration's invoice payloads are handled.
    """
    bot_id, environment = scope()
    async with get_db_connection() as db:
        if not await one(db, "SELECT id FROM payment_orders WHERE bot_id=? AND environment=? LIMIT 1", (bot_id, environment)):
            return
    offset = 0
    while True:
        page = await bot.get_star_transactions(offset=offset, limit=100, request_timeout=8)
        for transaction in page.transactions:
            partner = transaction.source or transaction.receiver
            if (getattr(partner, "type", None) != "user" or getattr(partner, "transaction_type", None) != "invoice_payment"
                    or not order_id_from(getattr(partner, "invoice_payload", None)) or transaction.nanostar_amount):
                continue
            try:
                await record_payment(partner.user.id, partner.invoice_payload, "XTR", abs(transaction.amount), transaction.id, refunded=transaction.receiver is not None)
            except PlatformError as error:
                logger.warning("Stars history receipt rejected: %s", type(error).__name__)
        if len(page.transactions) < 100:
            return
        offset += len(page.transactions)


async def payment_worker(bot):
    next_reconcile = 0.0
    while True:
        try:
            await refund_pending(bot)
            if time.monotonic() >= next_reconcile:
                next_reconcile = time.monotonic() + 60
                await reconcile(bot)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Stars recovery deferred: %s", type(error).__name__)
        await asyncio.sleep(2)
