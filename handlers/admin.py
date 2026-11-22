import os
import random
import string
import logging
from typing import List, Dict, Any
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from config import ADMIN_IDS
from states import AdminStates
from utils.parser import parse_admin_test_input, ParseError
from scripts.database.models import (
    create_test,
    add_question,
    get_tests_by_admin,
    get_test_by_id,
    get_questions_for_test,
    get_submissions_for_test,
)
from services.scoring_service import run_test_analytics_and_scoring
from services.platform_service import PlatformError
from services.excel_service import generate_test_report_excel
from keyboards.inline import (
    get_admin_test_control_keyboard,
    get_tests_list_keyboard,
    get_mini_app_keyboard,
)
from keyboards.reply import get_main_menu_keyboard

logger = logging.getLogger(__name__)
router = Router()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def generate_test_code() -> str:
    # 4-digit code e.g. 7421 or T-7421
    nums = "".join(random.choices(string.digits, k=4))
    return f"T-{nums}"


@router.message(F.text == "➕ Yangi test yaratish")
@router.message(Command("newtest"))
async def cmd_new_test_prompt(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("Sizda admin huquqi mavjud emas!")
        return

    # Check if text contains the full test definition directly
    text_content = message.text.strip()
    if text_content.startswith("/newtest") and len(text_content.splitlines()) > 4:
        # User supplied the test right in the command
        await process_admin_test_text(message, text_content, state)
        return

    keyboard = get_mini_app_keyboard()
    if keyboard:
        from handlers.import_upload import prompt_import
        await prompt_import(message, state)
        return

    help_template = (
        "📝 <b>Yangi test yaratish uchun savollar ro'yxatini yuboring.</b>\n\n"
        "<b>Talablar:</b>\n"
        "• Savollar soni: <b>5 tadan 44 tagacha</b>\n"
        "• Ochiq savollar: <b>ko'pi bilan 9 tagacha</b>\n"
        "• Yopiq savollar uchun to'g'ri javob: <b>A, B, C, D</b>\n"
        "• Ochiq savollar uchun: <code>[OPEN] AI ko'rsatmasi</code>\n\n"
        "<b>Namuna:</b>\n"
        "<pre>"
        "Matematika va Ona tili 1-variant\n"
        "1. A\n"
        "2. B\n"
        "3. D\n"
        "4. [OPEN] O'quvchi fe'l so'z turkumiga 2 ta misol keltirishi shart.\n"
        "5. C\n"
        "</pre>\n"
        "<i>Shuningdek, Excel (.xlsx) faylini ham yuborishingiz mumkin.</i>\n\n"
        "Bekor qilish uchun /cancel buyrug'ini yuboring."
    )
    await state.set_state(AdminStates.waiting_for_test_input)
    await message.answer(help_template, parse_mode="HTML")


@router.message(AdminStates.waiting_for_test_input, Command("cancel"))
async def cancel_test_creation(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Test yaratish bekor qilindi.",
        reply_markup=get_main_menu_keyboard(message.from_user.id),
    )


@router.message(AdminStates.waiting_for_test_input, F.document)
async def process_admin_excel_upload(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return

    doc = message.document
    if not (doc.file_name.endswith(".xlsx") or doc.file_name.endswith(".xls")):
        await message.answer("Iltimos, faqat .xlsx formatidagi Excel fayl yuboring!")
        return

    from openpyxl import load_workbook
    import io

    file_bytes = await bot.download(doc.file_id)
    try:
        wb = load_workbook(filename=io.BytesIO(file_bytes.read()))
        ws = wb.active

        # Expected format:
        # Col A: Number, Col B: Type ('closed'/'open'), Col C: Key/Rubric
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            await message.answer("Excel fayl bo'sh!")
            return

        # Build text string to pass into parser
        test_lines = [doc.file_name.replace(".xlsx", "")]
        # Skip header if first row has string titles
        start_row = 1 if isinstance(rows[0][0], str) and not rows[0][0].isdigit() else 0

        for r in rows[start_row:]:
            if not r or r[0] is None:
                continue
            q_num = str(r[0]).strip()
            q_type = str(r[1]).strip().lower() if len(r) > 1 and r[1] else "closed"
            ans_or_rubric = str(r[2]).strip() if len(r) > 2 and r[2] else ""

            if "open" in q_type or "ochiq" in q_type:
                test_lines.append(f"{q_num}. [OPEN] {ans_or_rubric}")
            else:
                test_lines.append(f"{q_num}. {ans_or_rubric}")

        text_to_parse = "\n".join(test_lines)
        await process_admin_test_text(message, text_to_parse, state)
    except Exception as e:
        logger.error(f"Excel reading error: {e}", exc_info=True)
        await message.answer(f"Excel faylini o'qishda xatolik: {e}")


@router.message(AdminStates.waiting_for_test_input, F.text)
async def process_admin_text_input(message: Message, state: FSMContext):
    await process_admin_test_text(message, message.text, state)


async def process_admin_test_text(message: Message, text: str, state: FSMContext):
    try:
        title, questions = parse_admin_test_input(text)
    except ParseError as pe:
        await message.answer(f"❌ <b>Xatolik:</b>\n{str(pe)}", parse_mode="HTML")
        return

    # Count open questions
    open_count = sum(1 for q in questions if q["question_type"] == "open")

    # Generate unique test code
    code = generate_test_code()

    # Save to database
    test_id = await create_test(
        code=code,
        title=title,
        created_by=message.from_user.id,
        total_questions=len(questions),
        open_questions_count=open_count,
    )

    for q in questions:
        await add_question(
            test_id=test_id,
            question_num=q["question_num"],
            question_type=q["question_type"],
            correct_answer=q["correct_answer"],
            ai_instructions=q["ai_instructions"],
        )

    await state.clear()

    resp = (
        f"🎉 <b>Test muvaffaqiyatli yaratildi!</b>\n\n"
        f"📌 <b>Test kodi:</b> <code>{code}</code>\n"
        f"🏷 <b>Nomi:</b> {title}\n"
        f"🔢 <b>Jami savollar:</b> {len(questions)} ta\n"
        f"🤖 <b>AI ochiq savollari:</b> {open_count} ta\n\n"
        f"📢 <i>O'quvchilarga ushbu kodni bering:</i> <code>{code}</code>\n"
        f"O'quvchilar botga kirib ushbu kod orqali test topshira oladilar."
    )
    await message.answer(
        resp,
        reply_markup=get_admin_test_control_keyboard(test_id, "active"),
        parse_mode="HTML",
    )


@router.message(F.text == "📊 Testlar boshqaruvi")
@router.message(Command("tests"))
async def cmd_list_tests(message: Message):
    if not is_admin(message.from_user.id):
        return

    tests = await get_tests_by_admin(message.from_user.id)
    if not tests:
        await message.answer(
            "Sizda hali yaratilgan testlar mavjud emas. '➕ Yangi test yaratish' tugmasidan foydalaning."
        )
        return

    await message.answer(
        "📋 <b>Sizning testlaringiz:</b>\nKerakli testni tanlang:",
        reply_markup=get_tests_list_keyboard(tests),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("view_test:"))
async def cb_view_test(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat berilmagan!", show_alert=True)
        return

    test_id = int(callback.data.split(":")[1])
    test = await get_test_by_id(test_id)
    if not test or test["created_by"] != callback.from_user.id:
        await callback.answer("Test topilmadi!", show_alert=True)
        return

    submissions = await get_submissions_for_test(test_id)
    status_str = "🟢 Faol (javoblar qabul qilinmoqda)" if test["status"] == "active" else "🏁 Yakunlangan"

    text = (
        f"📋 <b>Test ma'lumotlari:</b>\n\n"
        f"📌 <b>Kod:</b> <code>{test['code']}</code>\n"
        f"🏷 <b>Nomi:</b> {test['title']}\n"
        f"📊 <b>Holati:</b> {status_str}\n"
        f"❓ <b>Savollar:</b> {test['total_questions']} ta ({test['open_questions_count']} ta ochiq)\n"
        f"👥 <b>Topshirganlar soni:</b> {len(submissions)} nafar\n"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_admin_test_control_keyboard(test_id, test["status"]),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("refresh_test:"))
async def cb_refresh_test(callback: CallbackQuery):
    await cb_view_test(callback)


@router.callback_query(F.data.startswith("download_excel:"))
async def cb_download_excel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat berilmagan!", show_alert=True)
        return

    test_id = int(callback.data.split(":")[1])
    test = await get_test_by_id(test_id)
    if not test or test["created_by"] != callback.from_user.id or test["status"] != "finished":
        await callback.answer("Hisobot faqat o'zingizning yakunlangan testingiz uchun mumkin.", show_alert=True)
        return
    await callback.answer("Excel fayl tayyorlanmoqda...")
    try:
        excel_path = await generate_test_report_excel(test_id)
        test = await get_test_by_id(test_id)
        doc = FSInputFile(excel_path, filename=f"Test_{test['code']}_Natijalari.xlsx")
        await callback.message.answer_document(
            doc,
            caption=f"📊 <b>{test['code']}</b> - {test['title']} bo'yicha hisobot.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error sending excel: {e}", exc_info=True)
        await callback.message.answer(f"Excel faylini yaratishda xatolik: {e}")


@router.callback_query(F.data.startswith("finish_test:"))
async def cb_finish_test(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat berilmagan!", show_alert=True)
        return

    test_id = int(callback.data.split(":")[1])
    test = await get_test_by_id(test_id)
    if not test or test["created_by"] != callback.from_user.id:
        await callback.answer("Test topilmadi!", show_alert=True)
        return

    if test["status"] == "finished":
        await callback.answer("Bu test allaqachon yakunlangan!", show_alert=True)
        return

    await callback.answer("Ballar hisoblanmoqda va hisobot tayyorlanmoqda...")
    await callback.message.edit_text("⏳ <i>Natijalar hisoblanmoqda va taqsimlanmoqda...</i>", parse_mode="HTML")

    # 1. Run Analytics & tertile scoring
    try:
        analytics = await run_test_analytics_and_scoring(test_id, finish=True, owner_id=callback.from_user.id)
    except PlatformError as error:
        await callback.message.edit_text(str(error), parse_mode=None)
        return

    # 3. Generate Excel file
    excel_path = await generate_test_report_excel(test_id)

    # 4. Fetch updated questions and submissions
    questions = await get_questions_for_test(test_id)
    submissions = await get_submissions_for_test(test_id)

    # 5. Build summary text for admin
    q_tier_summary = []
    for q in questions:
        tier_symbol = {
            "easy": "🟢 1.1 ball (oson)",
            "medium": "🟡 1.7 ball (o'rta)",
            "hard": "🔴 2.5 ball (qiyin)",
            "open": "🤖 2.5 ball (ochiq)",
        }.get(q["assigned_tier"], f"{q['assigned_points']} ball")
        q_tier_summary.append(f"• {q['question_num']}-savol: {tier_symbol} ({q.get('correct_count', 0)} ta to'g'ri)")

    admin_summary = (
        f"🏁 <b>Test muvaffaqiyatli yakunlandi!</b>\n\n"
        f"📌 <b>Test:</b> {test['code']} - {test['title']}\n"
        f"👥 <b>Qatnashchilar:</b> {len(submissions)} nafar\n\n"
        f"📊 <b>Savollar bo'yicha berilgan ballar:</b>\n"
        + "\n".join(q_tier_summary[:15])  # show first 15 in message to avoid length limits
    )
    if len(q_tier_summary) > 15:
        admin_summary += f"\n<i>... va yana {len(q_tier_summary) - 15} ta savol (Excelda to'liq)</i>"

    # Send admin report
    await callback.message.edit_text(
        admin_summary,
        reply_markup=get_admin_test_control_keyboard(test_id, "finished"),
        parse_mode="HTML",
    )

    doc = FSInputFile(excel_path, filename=f"Yakuniy_Hisobot_{test['code']}.xlsx")
    await callback.message.answer_document(
        doc,
        caption=f"📁 <b>{test['code']}</b> testining to'liq statistikasi va reytingi.",
        parse_mode="HTML"
    )

    # Final student notifications are delivered by the durable job worker.
