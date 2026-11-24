"""Payment events must be routed before legacy answer/FSM message handlers."""

import asyncio
import logging
from html import escape

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, PreCheckoutQuery

from services import stars_payments as stars
from services.platform_service import PlatformError

router = Router()
logger = logging.getLogger(__name__)


@router.pre_checkout_query(F.invoice_payload.startswith(stars.PREFIX))
async def pre_checkout(query: PreCheckoutQuery, bot: Bot):
    try:
        await asyncio.wait_for(stars.validate_checkout(query.from_user.id, query.invoice_payload,
            query.currency, query.total_amount, query.id), timeout=5)
        await bot.answer_pre_checkout_query(query.id, ok=True, request_timeout=3)
    except PlatformError as error:
        await bot.answer_pre_checkout_query(query.id, ok=False, error_message=str(error), request_timeout=3)
    except Exception as error:
        logger.warning("Stars checkout rejected: %s", type(error).__name__)
        await bot.answer_pre_checkout_query(query.id, ok=False, error_message="To‘lovni tekshirib bo‘lmadi. Keyinroq qayta urinib ko‘ring.", request_timeout=3)


@router.message((F.successful_payment.currency == "XTR") & F.successful_payment.invoice_payload.startswith(stars.PREFIX))
async def successful_payment(message: Message):
    payment = message.successful_payment
    # Commit before sending any user-facing acknowledgement. The periodic
    # transaction scan recovers interrupted / already-acknowledged updates.
    result = await stars.record_payment(message.from_user.id, payment.invoice_payload,
        payment.currency, payment.total_amount, payment.telegram_payment_charge_id)
    if result["status"] == "paid":
        text = "✅ Stars sinov to‘lovi qabul qilindi. Testlar bepul qoladi. Tarix va qaytarish: Mini App → Profil."
    else:
        text = "Stars to‘lovi qaytarilmoqda yoki allaqachon qaytarilgan. Holat: Mini App → Profil."
    await message.answer(text)


@router.message((F.refunded_payment.currency == "XTR") & F.refunded_payment.invoice_payload.startswith(stars.PREFIX))
async def refunded_payment(message: Message):
    payment = message.refunded_payment
    await stars.record_payment(message.from_user.id, payment.invoice_payload,
        payment.currency, payment.total_amount, payment.telegram_payment_charge_id, refunded=True)
    await message.answer("✅ Stars qaytarilishi tasdiqlandi. Holat: Mini App → Profil.")


@router.message(Command("terms"))
async def terms(message: Message):
    await message.answer("<b>Stars sinov to‘lovi shartlari</b>\n\n" + escape(stars.TERMS_TEXT)
                         + "\n\nVersiya: <code>" + stars.TERMS_VERSION + "</code>")


@router.message(Command("paysupport", "support"))
async def pay_support(message: Message):
    contact = stars.support_url()
    if contact:
        await message.answer("<b>To‘lov bo‘yicha yordam</b>\n\nBuyurtma raqami va muammo tavsifini "
            + escape(contact) + " manziliga yuboring. Karta ma’lumotlari yoki token yubormang. "
            "Buyurtmalar va Starsni qaytarish: Mini App → Profil. Telegram yordam xizmati bu xaridlarni boshqarmaydi.")
    else:
        await message.answer("To‘lovlar yoqilmagan: yordam manzili hali sozlanmagan. Avvalgi sinov to‘lovlari tarixi va qaytarish: Mini App → Profil.")
