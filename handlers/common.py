from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from keyboards.reply import get_main_menu_keyboard
from keyboards.inline import get_mini_app_keyboard
from html import escape
import config

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if (message.text or "").split(maxsplit=1)[-1] == "import":
        from handlers.import_upload import prompt_import
        await prompt_import(message, state)
        return
    await state.clear()
    text = (
        f"Assalomu alaykum, <b>{escape(message.from_user.first_name)}</b>!\n\n"
        "<b>Basirat ta’lim markaziga xush kelibsiz.</b>\n"
        "Bilimingizni sinang va natijangizni kuzating.\n\n"
        "Boshlash uchun quyidagi <b>📚 Basirat testlari</b> tugmasini bosing. "
        "Ilovada o‘qituvchingiz bergan test kodini kiriting va savollarga javob bering.\n\n"
        "O‘qituvchilar shu ilovada test tayyorlashi, javoblarni tekshirishi va hisobot olishi mumkin."
    ) if config.MINI_APP_URL else (
        f"Assalomu alaykum, <b>{escape(message.from_user.first_name)}</b>!\n\n"
        "Ushbu bot orqali test topshirishingiz va natijalarni bilib olishingiz mumkin.\n\n"
        "📌 Test topshirish uchun quyidagi <b>✍️ Test topshirish</b> tugmasini bosing yoki "
        "o'qituvchi bergan test kodini yuboring."
    )
    await message.answer(
        text,
        reply_markup=get_main_menu_keyboard(message.from_user.id),
        parse_mode="HTML",
    )
    keyboard = get_mini_app_keyboard()
    if keyboard:
        await message.answer("<b>Basirat testlar</b>\nSavollar, javoblar va natijalar — bir joyda.", reply_markup=keyboard)


@router.message(F.text == "ℹ️ Bot haqida va qo'llanma")
@router.message(Command("help"))
async def cmd_help(message: Message):
    if config.MINI_APP_URL:
        await message.answer(
            "<b>Basirat · Foydalanish qo‘llanmasi</b>\n\n"
            "<b>O‘quvchilar uchun</b>\n"
            "1. <b>📚 Basirat testlari</b> tugmasini yoki bot menyusidagi <b>Testlar</b> tugmasini bosing.\n"
            "2. O‘qituvchingiz bergan test kodini kiriting.\n"
            "3. Variantni tanlang yoki ochiq javobingizni yozing. Javoblar avtomatik saqlanadi.\n"
            "4. <b>Javoblarim</b> bo‘limida tekshirib, <b>Tasdiqlash va topshirish</b> tugmasini bosing.\n\n"
            "To‘g‘ri va noto‘g‘ri javoblar topshirgach ko‘rinadi. Ochiq javoblar tekshirilishi kutilishi mumkin. "
            "Yakuniy ball va reyting o‘qituvchi testni yakunlagach ochiladi.\n\n"
            "<b>O‘qituvchilar uchun</b>\n"
            "Ilovadagi <b>O‘qituvchi</b> bo‘limini oching. PDF yoki rasmlarni botga yuboring "
            "yoki qurilmadan yuklang. Rasmlarni yuborib bo‘lgach, /done yozing. "
            "AI ajratgan savollar, matnlar va javob mezonlarini tekshiring, so‘ng testni nashr qiling. "
            "Natijalar test sahifasida yangilanib boradi.\n\n"
            "<b>Muhim:</b> javoblar bir marta topshiriladi. Tasdiqlashdan oldin tekshirib chiqing.",
            reply_markup=get_mini_app_keyboard(),
        )
        return
    text = (
        "📖 <b>Botdan foydalanish qo'llanmasi:</b>\n\n"
        "<b>O'quvchilar uchun:</b>\n"
        "1. <b>✍️ Test topshirish</b> tugmasini bosing.\n"
        "2. O'qituvchi bergan test kodini kiriting (masalan: <code>T-101</code>).\n"
        "3. Javoblarni tartib bilan yuboring:\n"
        "   Namuna:\n"
        "   <code>1. A\n2. B\n3. D\n4. Ochiq savol javobi matni\n5. C</code>\n"
        "   yoki: <code>1:A, 2:B, 3:D, 4:javob matni, 5:C</code>\n"
        "4. Bot javoblaringizni tekshirib, darhol qaysilari to'g'ri (✅) yoki noto'g'ri (❌) ekanligini ko'rsatadi.\n"
        "5. Test yakunlangach, to'plagan yakuniy ballingiz va o'rningiz xabar qilinadi.\n\n"
        "<b>Ballar tizimi (Yopiq savollar uchun):</b>\n"
        "• Ko'pchilik to'g'ri topgan oson savollar: <b>1.1 ball</b>\n"
        "• O'rtacha topilgan savollar: <b>1.7 ball</b>\n"
        "• Kamchilik topgan qiyin savollar: <b>2.5 ball</b>\n"
        "• Ochiq savollar: AI tomonidan tekshirilib, belgilangan ball beriladi."
    )
    await message.answer(text, parse_mode="HTML")


@router.callback_query(F.data == "cancel_sub")
async def cancel_submission(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Test topshirish bekor qilindi.")
    await callback.answer()
