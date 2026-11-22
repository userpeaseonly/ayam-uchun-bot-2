import logging
from typing import Dict, Any, List
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from states import StudentStates
from utils.parser import parse_student_answers, format_student_preview, ParseError
from scripts.database.models import (
    get_test_by_code,
    get_test_by_id,
    get_questions_for_test,
    get_submission,
)
from keyboards.inline import get_submission_confirm_keyboard, get_mini_app_keyboard
from html import escape
from services.platform_service import submit_answers, submission_result, PlatformError
from keyboards.reply import get_main_menu_keyboard

logger = logging.getLogger(__name__)
router = Router()


import re
from states import AdminStates


@router.message(F.text == "✍️ Test topshirish")
@router.message(Command("test"))
async def cmd_join_test(message: Message, state: FSMContext):
    await state.clear()
    
    # Check if test code was passed in command: /test T-1234
    if message.text and message.text.startswith("/"):
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1 and parts[1].strip():
            code = parts[1].strip().upper()
            await process_test_code_input(message, code, state)
            return

    await state.set_state(StudentStates.waiting_for_test_code)
    await message.answer(
        "✍️ <b>Test topshirish:</b>\n\n"
        "O'qituvchi bergan test kodini kiriting (masalan: <code>T-1234</code>):",
        parse_mode="HTML"
    )


# Allow entering test code directly at any time (e.g. "T-7620" or "7620")
@router.message(F.text.regexp(r"^([tT]-)?\d{4,6}$"))
async def handle_direct_test_code(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state in (
        StudentStates.waiting_for_answers,
        StudentStates.confirming_submission,
        AdminStates.waiting_for_test_input,
    ):
        return

    code = message.text.strip().upper()
    if not code.startswith("T-") and code.isdigit():
        test = await get_test_by_code(code)
        if not test:
            code = f"T-{code}"
    await process_test_code_input(message, code, state)


@router.message(StudentStates.waiting_for_test_code, F.text)
async def process_test_code(message: Message, state: FSMContext):
    raw_text = message.text.strip()

    # Check if user sent test code together with answers e.g. "T-7620\n1:A, 2:B..."
    code_match = re.match(r"^(?:TEST\s*)?((?:T-)?\d{4,6})(?:\s+|\n|:)(.*)$", raw_text, re.DOTALL | re.IGNORECASE)
    if code_match:
        code = code_match.group(1).upper()
        if not code.startswith("T-") and code.isdigit():
            code = f"T-{code}"
        remainder = code_match.group(2).strip()
        test = await get_test_by_code(code)
        if test:
            await process_test_code_input(message, code, state)
            if remainder and any(sep in remainder for sep in (":", ".", ")", "-")):
                message.text = remainder
                await process_student_answers_text(message, state)
            return

    code = raw_text.upper()
    if not code.startswith("T-") and code.isdigit():
        test = await get_test_by_code(code)
        if not test:
            code = f"T-{code}"
    await process_test_code_input(message, code, state)


async def process_test_code_input(message: Message, code: str, state: FSMContext):
    test = await get_test_by_code(code)
    if not test:
        await message.answer(
            f"❌ <code>{code}</code> kodli test topilmadi!\n"
            "Kodni to'g'ri kiritganingizni tekshirib, qayta urinib ko'ring.",
            parse_mode="HTML"
        )
        return

    if test["status"] != "active":
        await message.answer(
            f"⚠️ Ushbu test (<b>{test['code']}</b>) allaqachon yakunlangan va yangi javoblar qabul qilinmaydi.",
            parse_mode="HTML"
        )
        await state.clear()
        return

    # Check if student has already submitted
    existing = await get_submission(test["id"], message.from_user.id)
    if existing:
        await message.answer(
            f"⚠️ Siz <b>{test['code']}</b> testiga allaqachon javoblaringizni topshirgansiz.\n"
            "Qoidaga ko'ra faqat bir marta topshirish mumkin.\n"
            "Natijalar o'qituvchi testni yakunlaganida e'lon qilinadi.",
            parse_mode="HTML"
        )
        await state.clear()
        return

    if test.get("document_json"):
        keyboard = get_mini_app_keyboard(test["code"])
        if keyboard:
            await state.clear()
            await message.answer("📱 Savollar va javoblar uchun Mini App'ni oching:", reply_markup=keyboard)
            return

    questions = await get_questions_for_test(test["id"])
    open_count = test["open_questions_count"]

    await state.update_data(test_id=test["id"], code=test["code"])
    await state.set_state(StudentStates.waiting_for_answers)

    sample_text = (
        "1. A\n2. B\n3. D\n4. Ochiq savol javobi matni\n5. C"
        if open_count > 0 else
        "1. A\n2. B\n3. C\n4. D\n5. A"
    )

    info_msg = (
        f"📋 <b>Test: {test['code']} - {test['title']}</b>\n\n"
        f"🔢 Jami savollar soni: <b>{test['total_questions']} ta</b>\n"
        f"🤖 Ochiq savollar: <b>{open_count} ta</b>\n\n"
        f"📝 <b>Javoblaringizni quyidagi tartibda bitta xabarda yuboring:</b>\n\n"
        f"<pre>{sample_text}</pre>\n"
        f"<i>Yoki vergul bilan: <code>1:A, 2:B, 3:D, 4:javob matni, 5:C</code></i>\n\n"
        f"Javoblaringizni kuting va yuboring:"
    )
    await message.answer(info_msg, parse_mode="HTML")


@router.message(StudentStates.waiting_for_answers, F.text)
async def process_student_answers_text(message: Message, state: FSMContext):
    data = await state.get_data()
    test_id = data.get("test_id")
    if not test_id:
        await state.clear()
        await message.answer("Sessiya vaqti tugagan. Qaytadan '✍️ Test topshirish' tugmasini bosing.")
        return

    questions = await get_questions_for_test(test_id)
    try:
        parsed_answers = parse_student_answers(message.text, len(questions))
    except ParseError as pe:
        await message.answer(f"❌ <b>Xatolik:</b>\n{str(pe)}", parse_mode="HTML")
        return

    # Generate preview
    preview_text, is_complete = format_student_preview(parsed_answers, questions)
    
    # Save answers temporarily in FSM state
    # Store with string keys for JSON serialization compatibility
    str_key_answers = {str(k): v for k, v in parsed_answers.items()}
    await state.update_data(parsed_answers=str_key_answers)
    await state.set_state(StudentStates.confirming_submission)

    await message.answer(
        preview_text,
        reply_markup=get_submission_confirm_keyboard(test_id),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("edit_sub:"))
async def cb_edit_answers(callback: CallbackQuery, state: FSMContext):
    await state.set_state(StudentStates.waiting_for_answers)
    await callback.message.edit_text(
        "✏️ <b>Javoblaringizni qaytadan yuboring:</b>\n"
        "Barcha javoblarni to'g'rilab, bitta xabar ko'rinishida yozing.",
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_sub:"))
async def cb_confirm_submission(callback: CallbackQuery, state: FSMContext, bot: Bot):
    test_id = int(callback.data.split(":")[1])
    test = await get_test_by_id(test_id)
    if not test or test["status"] != "active":
        await callback.answer("Bu test faol emas yoki yakunlangan!", show_alert=True)
        await state.clear()
        return

    user = callback.from_user
    # Check if already submitted
    existing = await get_submission(test_id, user.id)
    if existing:
        await callback.answer("Siz bu testga allaqachon javob berdingiz!", show_alert=True)
        await state.clear()
        return

    data = await state.get_data()
    str_key_answers = data.get("parsed_answers", {})
    if not str_key_answers:
        await callback.answer("Javoblar topilmadi, qaytadan kiriting.", show_alert=True)
        await state.set_state(StudentStates.waiting_for_answers)
        return

    answers_dict = {int(k): v for k, v in str_key_answers.items()}

    await callback.message.edit_text(
        "⏳ <b>Javoblaringiz qabul qilinmoqda...</b>\n"
        "<i>Ochiq savollar AI tomonidan tekshirilmoqda, iltimos bir necha soniya kuting...</i>",
        parse_mode="HTML"
    )

    if data.get("test_id") != test_id:
        await callback.answer("Sessiya boshqa testga tegishli. Qayta oching.", show_alert=True)
        return
    try:
        await submit_answers(test_id, user.model_dump(), {str(k): v for k, v in answers_dict.items()})
    except PlatformError as error:
        await callback.message.edit_text(escape(str(error)))
        await callback.answer()
        return
    result = await submission_result(test_id, user.id)
    feedback_lines = [f"{a['number']}. " + ("⏳ Tekshirilmoqda" if a["correct"] is None else "✅ To'g'ri" if a["correct"] else "❌ Noto'g'ri") for a in result["answers"]]
    await state.clear()
    await callback.message.edit_text(
        "✅ <b>Javoblaringiz saqlandi!</b>\n\n" + "\n".join(feedback_lines)
        + "\n\nBall va o'rin test yakunlangach e'lon qilinadi.", parse_mode="HTML",
    )
    await callback.answer()


@router.message(F.text.regexp(r"(?:\b\d{1,2}\s*[\.:\)\-]\s*[a-zA-Z\w])"))
async def handle_answers_without_test_code(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer(
            "⚠️ <b>Siz hali test kodini kiritmadingiz!</b>\n\n"
            "Javoblarni yuborishdan oldin o'qituvchi bergan test kodini yuboring (masalan: <code>T-1234</code>) "
            "yoki <b>✍️ Test topshirish</b> tugmasini bosing.",
            parse_mode="HTML"
        )

