from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
import config
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def get_mini_app_url(code="", *, import_id="", teacher=False):
    if not config.MINI_APP_URL:
        return None
    url = urlsplit(config.MINI_APP_URL)
    query = dict(parse_qsl(url.query))
    if code:
        query["test"] = code
    if teacher:
        query["view"] = "teacher"
    if import_id:
        query["import"] = import_id
    return urlunsplit(url._replace(query=urlencode(query)))


def get_mini_app_keyboard(code="", *, import_id="", teacher=False):
    target = get_mini_app_url(code, import_id=import_id, teacher=teacher)
    if not target:
        return None
    label = ("✏️ Testni tayyorlash" if import_id else "👩‍🏫 O‘qituvchi kabineti" if teacher
             else "📚 Testni ochish" if code else "📚 Basirat testlari")
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=label, web_app=WebAppInfo(url=target),
    )]])


def get_welcome_keyboard():
    keyboard = get_mini_app_keyboard()
    if keyboard:
        keyboard.inline_keyboard.extend(get_mini_app_keyboard(teacher=True).inline_keyboard)
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="ℹ️ Yordam", callback_data="basirat_help")])
    return keyboard


def get_submission_confirm_keyboard(test_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Tasdiqlash va jo'natish",
                    callback_data=f"confirm_sub:{test_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Qayta kiritish",
                    callback_data=f"edit_sub:{test_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data="cancel_sub",
                ),
            ],
        ]
    )


def get_admin_test_control_keyboard(test_id: int, status: str) -> InlineKeyboardMarkup:
    buttons = []
    if status == "active":
        buttons.append(
            [
                InlineKeyboardButton(
                    text="🏁 Testni yakunlash (Ballarni hisoblash)",
                    callback_data=f"finish_test:{test_id}",
                )
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(
                text="📥 Excel hisobotni yuklash",
                callback_data=f"download_excel:{test_id}",
            ),
            InlineKeyboardButton(
                text="🔄 Yangilash",
                callback_data=f"refresh_test:{test_id}",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_tests_list_keyboard(tests: list) -> InlineKeyboardMarkup:
    buttons = []
    for t in tests:
        status_icon = "🟢" if t["status"] == "active" else "🏁"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{status_icon} {t['code']} - {t['title'][:25]}",
                    callback_data=f"view_test:{t['id']}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)
