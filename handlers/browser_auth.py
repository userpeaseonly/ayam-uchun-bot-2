from html import escape

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from services import browser_auth
from services.platform_service import PlatformError
from services.web_payments import browser_url

router = Router()


async def prompt(message: Message, login_id):
    if message.chat.type != 'private':
        return
    try:
        item = await browser_auth.pending(login_id)
        await message.answer(f'<b>Brauzerda kirishni tasdiqlash</b>\n\nSayt: {escape(browser_url())}\n'
            f'Kod: <b>{item["code"]}</b>\n\nBrauzerdagi kod bilan solishtiring. '
            'Faqat o‘zingiz boshlagan kirishni tasdiqlang. Tasdiqlagach avvalgi brauzer oynasiga qayting.',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Kirishni tasdiqlash', callback_data='web_login:' + login_id)]]))
    except PlatformError as error:
        await message.answer(escape(str(error)))


@router.callback_query(F.data.startswith('web_login:'))
async def approve(query: CallbackQuery):
    if not query.message or query.message.chat.type != 'private':
        await query.answer('Shaxsiy chatdan foydalaning.', show_alert=True)
        return
    try:
        await browser_auth.approve(query.data.split(':', 1)[1], query.from_user.model_dump())
        await query.answer('Tasdiqlandi. Brauzerga qayting.')
        await query.message.edit_text('✅ Kirish tasdiqlandi. Kirishni boshlagan brauzer oynasiga qayting.')
    except PlatformError as error:
        await query.answer(str(error), show_alert=True)
