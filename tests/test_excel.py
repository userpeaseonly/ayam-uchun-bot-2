import pytest
import os
from openpyxl import load_workbook
from scripts.database.db import init_db
from scripts.database.models import (
    create_test,
    add_question,
    create_submission,
    add_answer,
)
from services.scoring_service import run_test_analytics_and_scoring
from services.excel_service import generate_test_report_excel


@pytest.mark.asyncio
async def test_excel_generation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    test_db = str(tmp_path / "test_excel.sqlite3")
    import config
    monkeypatch.setattr(config, "DB_PATH", test_db)

    await init_db()

    test_id = await create_test(
        code="EXC-101",
        title="Excel Testi",
        created_by=111,
        total_questions=5,
        open_questions_count=0,
    )
    q_ids = []
    for i in range(1, 6):
        qid = await add_question(test_id, i, "closed", correct_answer="A")
        q_ids.append(qid)

    sub_id = await create_submission(test_id, 2001, "Dilshod", "Alimov", "dilshod")
    for qid in q_ids:
        await add_answer(sub_id, qid, "A", is_correct=1)

    await run_test_analytics_and_scoring(test_id)

    excel_path = await generate_test_report_excel(test_id)
    assert os.path.exists(excel_path)

    wb = load_workbook(excel_path)
    sheet_names = wb.sheetnames
    assert "Natijalar Reytingi" in sheet_names
    assert "Savollar Tahlili" in sheet_names
    assert "Batafsil Javoblar" in sheet_names

    ws1 = wb["Natijalar Reytingi"]
    assert ws1.cell(row=2, column=2).value == "Dilshod Alimov"
