import pytest
import aiosqlite
from services.scoring_service import calculate_tertile_distribution, run_test_analytics_and_scoring
from scripts.database.db import init_db
from scripts.database.models import (
    create_test,
    add_question,
    create_submission,
    add_answer,
    get_submissions_for_test,
    get_questions_for_test,
)


def test_tertile_distribution_three_items():
    questions = [
        {"id": 101, "question_num": 1},
        {"id": 102, "question_num": 2},
        {"id": 103, "question_num": 3},
    ]
    # Q1: 10 correct, Q2: 5 correct, Q3: 1 correct
    counts = {101: 10, 102: 5, 103: 1}

    dist = calculate_tertile_distribution(questions, counts)
    assert dist[101] == ("easy", 1.1)
    assert dist[102] == ("medium", 1.7)
    assert dist[103] == ("hard", 2.5)


def test_tertile_distribution_six_items():
    questions = [{"id": i, "question_num": i} for i in range(1, 7)]
    # Correct counts: 20, 18, 15, 12, 8, 2
    counts = {1: 20, 2: 18, 3: 15, 4: 12, 5: 8, 6: 2}

    dist = calculate_tertile_distribution(questions, counts)
    assert dist[1] == ("easy", 1.1)
    assert dist[2] == ("easy", 1.1)
    assert dist[3] == ("medium", 1.7)
    assert dist[4] == ("medium", 1.7)
    assert dist[5] == ("hard", 2.5)
    assert dist[6] == ("hard", 2.5)


@pytest.mark.asyncio
async def test_full_scoring_flow(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test.sqlite3")
    import config
    monkeypatch.setattr(config, "DB_PATH", test_db)

    # Re-init DB
    await init_db()

    # 1. Create a test with 5 closed questions and 1 open question
    test_id = await create_test(
        code="TEST-999",
        title="Matematika Sinov",
        created_by=111,
        total_questions=6,
        open_questions_count=1,
    )

    # Add 5 closed questions
    q_ids = []
    for i in range(1, 6):
        qid = await add_question(
            test_id=test_id,
            question_num=i,
            question_type="closed",
            correct_answer="A",
        )
        q_ids.append(qid)

    # Add 1 open question
    open_qid = await add_question(
        test_id=test_id,
        question_num=6,
        question_type="open",
        ai_instructions="Must describe gravity",
        assigned_points=2.5,
    )
    q_ids.append(open_qid)

    # 2. Student 1: Answers all 5 closed correct + open correct
    sub1_id = await create_submission(test_id, 1001, "Ali", "Valiyev", "ali")
    for qid in q_ids[:5]:
        await add_answer(sub1_id, qid, "A", is_correct=1)
    await add_answer(sub1_id, open_qid, "Gravity pulls down", is_correct=1)

    # 3. Student 2: Answers Q1, Q2 correct, Q3, Q4, Q5 wrong, open wrong
    sub2_id = await create_submission(test_id, 1002, "Bobur", "Zokirov", "bobur")
    for qid in q_ids[:2]:
        await add_answer(sub2_id, qid, "A", is_correct=1)
    for qid in q_ids[2:5]:
        await add_answer(sub2_id, qid, "B", is_correct=0)
    await add_answer(sub2_id, open_qid, "Wrong answer", is_correct=0)

    # 4. Student 3: Answers Q1 correct, Q2-Q5 wrong, open correct
    sub3_id = await create_submission(test_id, 1003, "Charos", "Karimova", "charos")
    await add_answer(sub3_id, q_ids[0], "A", is_correct=1)
    for qid in q_ids[1:5]:
        await add_answer(sub3_id, qid, "C", is_correct=0)
    await add_answer(sub3_id, open_qid, "Gravity pulls down", is_correct=1)

    # Run analytics and scoring
    analytics = await run_test_analytics_and_scoring(test_id)
    assert analytics["total_participants"] == 3
    assert analytics["closed_count"] == 5
    assert analytics["open_count"] == 1

    # Check question point tiers
    # Q1 correct count = 3 (most answered) -> easy (1.1 pts)
    # Q2 correct count = 2 -> easy or medium
    # Q3, Q4, Q5 correct count = 1 -> hard (2.5 pts)
    updated_questions = await get_questions_for_test(test_id)
    q1 = next(q for q in updated_questions if q["question_num"] == 1)
    assert q1["assigned_points"] == 1.1

    # Check student submissions
    subs = await get_submissions_for_test(test_id)
    # Ali should be rank 1
    ali = next(s for s in subs if s["user_id"] == 1001)
    assert ali["rank"] == 1
    assert ali["total_correct"] == 6
    assert ali["total_score"] > 0
