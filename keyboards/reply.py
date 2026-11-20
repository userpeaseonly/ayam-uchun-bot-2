from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from config import ADMIN_IDS


def get_main_menu_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    is_admin = user_id in ADMIN_IDS
    buttons = [
        [KeyboardButton(text="✍️ Test topshirish")],
    ]
    if is_admin:
        buttons.insert(0, [KeyboardButton(text="➕ Yangi test yaratish"), KeyboardButton(text="📊 Testlar boshqaruvi")])
    buttons.append([KeyboardButton(text="ℹ️ Bot haqida va qo'llanma")])

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
