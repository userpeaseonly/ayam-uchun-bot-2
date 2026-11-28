from typing import Optional, List, Dict, Any, Tuple
from scripts.database.db import get_db_connection


async def create_test(
    code: str,
    title: str,
    created_by: int,
    total_questions: int,
    open_questions_count: int,
    *, scoring_method: str = "rasch_v1",
) -> int:
    async with get_db_connection() as db:
        cursor = await db.execute(
            """
            INSERT INTO tests (code, title, created_by, total_questions, open_questions_count, status, public_id, scoring_method)
            VALUES (?, ?, ?, ?, ?, 'active', lower(hex(randomblob(16))), ?)
            """,
            (code.upper(), title, created_by, total_questions, open_questions_count, scoring_method),
        )
        await db.commit()
        return cursor.lastrowid


async def get_test_by_code(code: str) -> Optional[Dict[str, Any]]:
    async with get_db_connection() as db:
        cursor = await db.execute(
            "SELECT * FROM tests WHERE code = ?", (code.strip().upper(),)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_test_by_id(test_id: int) -> Optional[Dict[str, Any]]:
    async with get_db_connection() as db:
        cursor = await db.execute("SELECT * FROM tests WHERE id = ?", (test_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_tests_by_admin(admin_id: int, limit: int = 15) -> List[Dict[str, Any]]:
    async with get_db_connection() as db:
        cursor = await db.execute(
            "SELECT * FROM tests WHERE created_by = ? ORDER BY id DESC LIMIT ?",
            (admin_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def finish_test(test_id: int):
    async with get_db_connection() as db:
        await db.execute(
            "UPDATE tests SET status = 'finished', finished_at = CURRENT_TIMESTAMP WHERE id = ?",
            (test_id,),
        )
        await db.commit()


async def add_question(
    test_id: int,
    question_num: int,
    question_type: str,
    correct_answer: Optional[str] = None,
    ai_instructions: Optional[str] = None,
    assigned_points: Optional[float] = None,
) -> int:
    async with get_db_connection() as db:
        cursor = await db.execute(
            """
            INSERT INTO questions (test_id, question_num, question_type, correct_answer, ai_instructions, assigned_points)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                test_id,
                question_num,
                question_type,
                correct_answer.upper() if correct_answer else None,
                ai_instructions,
                assigned_points,
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def get_questions_for_test(test_id: int) -> List[Dict[str, Any]]:
    async with get_db_connection() as db:
        cursor = await db.execute(
            "SELECT * FROM questions WHERE test_id = ? ORDER BY question_num ASC",
            (test_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def create_submission(
    test_id: int,
    user_id: int,
    first_name: Optional[str],
    last_name: Optional[str],
    username: Optional[str],
) -> int:
    async with get_db_connection() as db:
        cursor = await db.execute(
            """
            INSERT INTO submissions (test_id, user_id, first_name, last_name, username)
            VALUES (?, ?, ?, ?, ?)
            """,
            (test_id, user_id, first_name, last_name, username),
        )
        await db.commit()
        return cursor.lastrowid


async def get_submission(test_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    async with get_db_connection() as db:
        cursor = await db.execute(
            "SELECT * FROM submissions WHERE test_id = ? AND user_id = ?",
            (test_id, user_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_submissions_for_test(test_id: int) -> List[Dict[str, Any]]:
    async with get_db_connection() as db:
        cursor = await db.execute(
            "SELECT * FROM submissions WHERE test_id = ? ORDER BY total_score DESC, total_correct DESC",
            (test_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def add_answer(
    submission_id: int,
    question_id: int,
    user_answer: str,
    is_correct: int,
    points_awarded: float = 0.0,
    ai_feedback: Optional[str] = None,
) -> int:
    async with get_db_connection() as db:
        cursor = await db.execute(
            """
            INSERT INTO answers (submission_id, question_id, user_answer, is_correct, points_awarded, ai_feedback)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (submission_id, question_id, user_answer, is_correct, points_awarded, ai_feedback),
        )
        await db.commit()
        return cursor.lastrowid


async def get_answers_for_submission(submission_id: int) -> List[Dict[str, Any]]:
    async with get_db_connection() as db:
        cursor = await db.execute(
            """
            SELECT a.*, q.question_num, q.question_type, q.correct_answer, q.assigned_points
            FROM answers a
            JOIN questions q ON a.question_id = q.id
            WHERE a.submission_id = ?
            ORDER BY q.question_num ASC
            """,
            (submission_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_all_answers_for_test(test_id: int) -> List[Dict[str, Any]]:
    async with get_db_connection() as db:
        cursor = await db.execute(
            """
            SELECT a.*, s.user_id, s.first_name, s.last_name, s.username,
                   q.question_num, q.question_type, q.correct_answer
            FROM answers a
            JOIN submissions s ON a.submission_id = s.id
            JOIN questions q ON a.question_id = q.id
            WHERE s.test_id = ?
            ORDER BY s.id, q.question_num
            """,
            (test_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def batch_update_question_stats(
    updates: List[Tuple[int, str, float, int]]
):
    """updates is list of (correct_count, tier, points, question_id)"""
    if not updates:
        return
    async with get_db_connection() as db:
        await db.executemany(
            """
            UPDATE questions
            SET correct_count = ?, assigned_tier = ?, assigned_points = ?
            WHERE id = ?
            """,
            updates,
        )
        await db.commit()


async def batch_update_submission_scores(
    updates: List[Tuple[int, float, int, int]]
):
    """updates is list of (total_correct, total_score, rank, submission_id)"""
    if not updates:
        return
    async with get_db_connection() as db:
        await db.executemany(
            """
            UPDATE submissions
            SET total_correct = ?, total_score = ?, rank = ?
            WHERE id = ?
            """,
            updates,
        )
        await db.commit()


async def batch_update_answer_points(updates: List[Tuple[float, int]]):
    """updates is list of (points_awarded, answer_id)"""
    if not updates:
        return
    async with get_db_connection() as db:
        await db.executemany(
            "UPDATE answers SET points_awarded = ? WHERE id = ?",
            updates,
        )
        await db.commit()
