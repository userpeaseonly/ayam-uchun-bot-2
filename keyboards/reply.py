from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from config import ADMIN_IDS
from keyboards.inline import get_mini_app_url


def get_main_menu_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    is_admin = user_id in ADMIN_IDS
    app_url = get_mini_app_url()
    if app_url:
        return ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="📚 Basirat testlari", web_app=WebAppInfo(url=app_url))],
            [KeyboardButton(text="📎 Test yuklash"), KeyboardButton(
                text="👩‍🏫 O‘qituvchi kabineti", web_app=WebAppInfo(url=get_mini_app_url(teacher=True)),
            )],
            [KeyboardButton(text="ℹ️ Yordam")],
        ], resize_keyboard=True, input_field_placeholder="Basirat · Bilim sari birga")
    buttons = [
        [KeyboardButton(text="✍️ Test topshirish")],
    ]
    if is_admin:
        buttons.insert(0, [KeyboardButton(text="➕ Yangi test yaratish"), KeyboardButton(text="📊 Testlar boshqaruvi")])
    buttons.append([KeyboardButton(text="ℹ️ Yordam")])

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
