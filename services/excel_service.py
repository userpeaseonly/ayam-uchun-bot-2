import os
import json
from typing import Dict, Any, List
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from scripts.database.models import (
    get_test_by_id,
    get_questions_for_test,
    get_submissions_for_test,
    get_all_answers_for_test,
)


def style_header_cell(cell, text: str, fill_color: str = "2F4F4F"):
    cell.value = text
    cell.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    cell.fill = PatternFill(start_color=fill_color, end_color=fill_color, fill_type="solid")
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


async def generate_test_report_excel(test_id: int) -> str:
    """
    Generates a beautifully styled Excel report for the finished test.
    Returns the file path to the generated .xlsx file.
    """
    test = await get_test_by_id(test_id)
    questions = await get_questions_for_test(test_id)
    submissions = await get_submissions_for_test(test_id)
    all_answers = await get_all_answers_for_test(test_id)
    rasch = test.get("scoring_method") == "rasch_v1"
    calibration = json.loads(test.get("scoring_json") or "{}") if rasch else {}

    # Prepare directories
    reports_dir = os.path.join(os.getcwd(), "reports")
    os.makedirs(reports_dir, exist_ok=True)
    filename = f"Test_Hisoboti_{test['code']}_{test_id}.xlsx"
    file_path = os.path.join(reports_dir, filename)

    wb = Workbook()
    thin_border = Border(
        left=Side(style='thin', color='D3D3D3'),
        right=Side(style='thin', color='D3D3D3'),
        top=Side(style='thin', color='D3D3D3'),
        bottom=Side(style='thin', color='D3D3D3')
    )

    # -------------------------------------------------------------
    # Sheet 1: Reyting va Natijalar (Leaderboard)
    # -------------------------------------------------------------
    ws1 = wb.active
    ws1.title = "Natijalar Reytingi"

    headers1 = [
        "O'rin",
        "O'quvchi (F.I)",
        "Telegram Username",
        "Telegram ID",
        "To'g'ri javoblar",
        "Umumiy Ball",
        "Topshirilgan vaqt"
    ]
    if rasch:
        headers1[5] = "Mashq natijasi (T-ball)"
        headers1 += ["Qobiliyat (logit)", "Posterior SD (logit)"]
    for col_idx, h in enumerate(headers1, 1):
        style_header_cell(ws1.cell(row=1, column=col_idx), h, "1E3D59")

    for row_idx, sub in enumerate(submissions, start=2):
        name = f"{sub.get('first_name') or ''} {sub.get('last_name') or ''}".strip() or "Noma'lum"
        username = f"@{sub['username']}" if sub.get('username') else "-"
        
        row_data = [
            sub.get("rank") if rasch else sub.get("rank") or (row_idx - 1),
            name,
            username,
            sub["user_id"],
            f"{sub.get('total_correct', 0)} / {test['total_questions']}",
            sub.get("total_score", 0.0),
            sub.get("submitted_at", "")
        ]
        if rasch:
            row_data += [sub.get("rasch_theta"), sub.get("rasch_se")]
        for col_idx, val in enumerate(row_data, 1):
            cell = ws1.cell(row=row_idx, column=col_idx, value=val)
            cell.border = thin_border
            cell.alignment = Alignment(
                horizontal="center" if col_idx in (1, 4, 5, 6, 7) else "left",
                vertical="center"
            )
            if col_idx == 6:
                cell.font = Font(bold=True)

    # -------------------------------------------------------------
    # Sheet 2: Savollar statistikasi (Question Analytics)
    # -------------------------------------------------------------
    ws2 = wb.create_sheet(title="Savollar Tahlili")
    headers2 = [
        "Savol №",
        "Savol Turi",
        "To'g'ri Kalit / Rubric",
        "To'g'ri Yechganlar",
        "Muvaffaqiyat (%)",
        "Qiyinlik Darajasi",
        "Belgilangan Ball"
    ]
    if rasch:
        headers2[-2:] = ["Qiyinlik (logit)", "Infit (EAP, tavsifiy)"]
    for col_idx, h in enumerate(headers2, 1):
        style_header_cell(ws2.cell(row=1, column=col_idx), h, "175873")

    total_subs = max(len(submissions), 1)

    tier_labels = {
        "easy": "Oson (Ko'pchilik topgan)",
        "medium": "O'rta (O'rtacha topilgan)",
        "hard": "Qiyin (Kamchilik topgan)",
        "open": "Ochiq savol (AI)"
    }

    for row_idx, q in enumerate(questions, start=2):
        correct_cnt = q.get("correct_count", 0)
        success_pct = round((correct_cnt / total_subs) * 100, 1)
        q_type_str = "Ochiq savol" if q["question_type"] == "open" else "Yopiq test"
        key_or_rubric = q["correct_answer"] if q["question_type"] == "closed" else (q["ai_instructions"] or "-")
        tier_str = tier_labels.get(q.get("assigned_tier", ""), q.get("assigned_tier") or "-")
        pts = q.get("assigned_points", 0.0)

        row_data = [
            q["question_num"],
            q_type_str,
            key_or_rubric,
            correct_cnt,
            f"{success_pct}%",
            tier_str,
            pts
        ]
        if rasch:
            row_data[-2:] = [q.get("difficulty_logit"), q.get("infit")]
        for col_idx, val in enumerate(row_data, 1):
            cell = ws2.cell(row=row_idx, column=col_idx, value=val)
            cell.border = thin_border
            cell.alignment = Alignment(
                horizontal="center" if col_idx in (1, 2, 4, 5, 7) else "left",
                vertical="center"
            )
            if col_idx == 7:
                cell.font = Font(bold=True)

    # -------------------------------------------------------------
    # Sheet 3: Batafsil javoblar jadvali (Grid of Student Responses)
    # -------------------------------------------------------------
    ws3 = wb.create_sheet(title="Batafsil Javoblar")
    headers3 = ["O'quvchi"] + [f"S{q['question_num']}" for q in questions]
    for col_idx, h in enumerate(headers3, 1):
        style_header_cell(ws3.cell(row=1, column=col_idx), h, "2B7A78")

    # Map submission_id -> {question_id: answer_row}
    sub_answers_map: Dict[int, Dict[int, Any]] = {}
    for a in all_answers:
        s_id = a["submission_id"]
        q_id = a["question_id"]
        if s_id not in sub_answers_map:
            sub_answers_map[s_id] = {}
        sub_answers_map[s_id][q_id] = a

    correct_fill = PatternFill(start_color="D4EDDA", end_color="D4EDDA", fill_type="solid")
    wrong_fill = PatternFill(start_color="F8D7DA", end_color="F8D7DA", fill_type="solid")

    for row_idx, sub in enumerate(submissions, start=2):
        name = f"{sub.get('first_name') or ''} {sub.get('last_name') or ''}".strip() or f"User {sub['user_id']}"
        name_cell = ws3.cell(row=row_idx, column=1, value=name)
        name_cell.border = thin_border
        name_cell.alignment = Alignment(horizontal="left", vertical="center")

        s_answers = sub_answers_map.get(sub["id"], {})
        for col_idx, q in enumerate(questions, start=2):
            ans = s_answers.get(q["id"])
            if ans:
                val = ans["user_answer"]
                # Student-controlled content must remain literal text in Excel.
                if isinstance(val, str) and val.lstrip().startswith(("=", "+", "-", "@")):
                    val = "'" + val
                is_corr = ans["is_correct"] == 1
                cell = ws3.cell(row=row_idx, column=col_idx, value=val)
                cell.border = thin_border
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.fill = correct_fill if is_corr else wrong_fill
            else:
                cell = ws3.cell(row=row_idx, column=col_idx, value="-")
                cell.border = thin_border
                cell.alignment = Alignment(horizontal="center", vertical="center")

    if rasch:
        audit = wb.create_sheet(title="Rash metodikasi")
        for label, value in [
            ("Natija", "Rash modeli asosidagi mashq natijasi; rasmiy sertifikat bali emas"),
            ("Versiya", calibration.get("version")),
            ("Holat", calibration.get("status", "pending")),
            ("Model", "1PL; diskriminatsiya = 1; MML N(0,1); EAP"),
            ("Qatnashchilar", calibration.get("participants")),
            ("Kalibrlangan savollar", calibration.get("informative_items")),
            ("Konvergensiya", calibration.get("converged")),
            ("Iteratsiyalar", calibration.get("iterations")),
            ("O‘rtacha theta", calibration.get("mean")),
            ("Theta standart tafovuti", calibration.get("sd")),
            ("EAP ishonchliligi (tavsifiy)", calibration.get("eap_reliability")),
            ("Formula", "T = 50 + 10 * (theta - guruh o‘rtachasi) / guruh standart tafovuti"),
            ("Cheklov", "Guruhga nisbiy T-ball; 75 bilan kesilmaydi; sessiyalararo tenglashtirilmagan"),
            ("Ochiq savollar", "To‘liq to‘g‘ri / noto‘g‘ri (0/1); esse va qisman ball hisoblanmaydi"),
            ("Noaniqlik", "Posterior SD item kalibrlash noaniqligini o‘z ichiga olmaydi"),
            ("Ogohlantirishlar", ", ".join(calibration.get("warnings", []))),
            ("Kvadratura", json.dumps(calibration.get("quadrature", {}))),
        ]:
            audit.append([label, value])
        # Keep the complete versioned snapshot inside the export, split below
        # Excel's 32,767-character per-cell limit for large cohorts.
        encoded = json.dumps(calibration, ensure_ascii=False, allow_nan=False)
        for start in range(0, len(encoded), 30000):
            audit.append([f"Kalibrlash JSON {start // 30000 + 1}", encoded[start:start + 30000]])

    # Auto-adjust column widths for all sheets
    for ws in wb.worksheets:
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = min(max(max_len + 4, 12), 80)

    wb.save(file_path)
    return file_path
