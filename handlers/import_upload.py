"""Teacher files can be sent or forwarded in Telegram without a web file picker."""

import logging

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
from keyboards.inline import get_mini_app_keyboard
from services.import_service import media_file
from services.platform_service import PlatformError
from services.upload_service import (
    LimitedDownload, active_collection, receive_telegram_source, start_collection,
    store_source, telegram_receipt, upload_locks,
)

router = Router()
logger = logging.getLogger(__name__)


def can_upload(message):
    return message.from_user and not getattr(message.from_user, "is_bot", False) and message.chat.type == "private"


async def prompt_import(message: Message, state: FSMContext):
    if not can_upload(message):
        await message.answer("Test fayllarini botning shaxsiy chatiga yuboring.")
        return
    await state.clear()
    await message.answer(
        "📎 <b>Test faylini shu chatga yuboring yoki boshqa chatdan forward qiling.</b>\n\n"
        "📄 PDF: yuborishingiz bilan AI savollarni ajratishni boshlaydi.\n"
        "🖼 Rasmlar: sahifalarni tartib bilan yuboring (albom ham mumkin). Hammasi yuborilgach, "
        "<b>Importni boshlash</b> tugmasini bosing yoki /done yozing.\n\n"
        "Jami 20 MB, ko'pi bilan 30 sahifa. Savollar va javoblarni Mini App'da tekshirib nashr qilasiz.",
        parse_mode="HTML", reply_markup=get_mini_app_keyboard(),
    )


@router.message(Command("import"))
async def cmd_import(message: Message, state: FSMContext):
    await prompt_import(message, state)


def collection_keyboard(import_id):
    rows = [[InlineKeyboardButton(text="✅ Importni boshlash", callback_data=f"start_import:{import_id}")]]
    review = get_mini_app_keyboard(import_id=import_id)
    if review:
        rows.extend(review.inline_keyboard)
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.document | F.photo)
async def receive_upload(message: Message, bot: Bot, state: FSMContext | None = None):
    document = message.document
    if document and (document.file_name or "").lower().endswith((".xlsx", ".xls")):
        raise SkipHandler()  # Preserve the existing Excel creation flow.
    if not can_upload(message):
        await message.answer("Test fayllarini botning shaxsiy chatiga yuboring.")
        return
    if document and not (
        (document.file_name or "").lower().endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp"))
        or document.mime_type in ("application/pdf", "image/jpeg", "image/png", "image/webp")
    ):
        await message.answer("PDF yoki JPG/PNG/WebP rasmini yuboring.")
        return
    attachment = document or message.photo[-1]
    if attachment.file_size and attachment.file_size > config.MAX_UPLOAD_BYTES:
        await message.answer("Fayl 20 MB dan oshmasin. PDF'ni kichraytirib qayta yuboring.")
        return
    source = None
    registered = False
    try:
        async with upload_locks[message.from_user.id]:
            receipt = await telegram_receipt(message.chat.id, message.message_id, message.from_user.id)
            if receipt:
                return  # A repeated Telegram update must not create another import.
            with LimitedDownload() as buffer:
                await bot.download(attachment.file_id, destination=buffer, timeout=60)
                source = await store_source(buffer.getvalue(), document.file_name if document else f"Sahifa-{message.message_id}.jpg")
            result = await receive_telegram_source(message.from_user.id, message.chat.id, message.message_id, source)
            registered = result["registered"]
        if state:
            await state.clear()
        if result["pdf"]:
            await message.answer(
                "📄 PDF qabul qilindi. AI savollarni ajratmoqda. Qoralamani Mini App'da oching; tayyor bo'lgach shu yerda ham xabar beramiz.",
                reply_markup=get_mini_app_keyboard(import_id=result["id"]),
            )
        elif result["first"]:
            await message.answer(
                "🖼 Rasmlar qabul qilinmoqda. Qolgan sahifalarni ham tartib bilan yuboring. "
                "Hammasi yuborilgach, quyidagi tugmani bosing yoki /done yozing.",
                reply_markup=collection_keyboard(result["id"]),
            )
    except PlatformError as error:
        await message.answer(str(error), parse_mode=None)
    except Exception as error:
        logger.warning("Telegram file intake failed (%s)", type(error).__name__)
        await message.answer("Faylni yuklab bo'lmadi. Qayta yuboring yoki /import buyrug'ini bosing.")
    finally:
        if source and not registered:
            media_file(source["filename"]).unlink(missing_ok=True)


@router.message(Command("done"))
async def cmd_done(message: Message):
    if not can_upload(message):
        return
    collection = await active_collection(message.from_user.id, message.chat.id)
    if not collection:
        await message.answer("Yig'ilayotgan rasmlar topilmadi. Avval PDF yoki rasmlarni yuboring.")
        return
    try:
        import_id = await start_collection(collection["import_id"], message.from_user.id)
        await message.answer("⏳ Rasmlar saqlandi. AI savollarni ajratmoqda.", reply_markup=get_mini_app_keyboard(import_id=import_id))
    except PlatformError as error:
        await message.answer(str(error), parse_mode=None)


@router.callback_query(F.data.startswith("start_import:"))
async def cb_start_import(callback: CallbackQuery):
    if not callback.message or callback.message.chat.type != "private":
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    # Acknowledge before waiting for an in-flight album download.
    await callback.answer("Rasmlar saqlanmoqda…")
    try:
        import_id = await start_collection(callback.data.split(":", 1)[1], callback.from_user.id)
        await callback.message.edit_text("⏳ Rasmlar saqlandi. AI savollarni ajratmoqda.", reply_markup=get_mini_app_keyboard(import_id=import_id))
    except PlatformError as error:
        await callback.message.answer(str(error), parse_mode=None)
