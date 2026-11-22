from typing import List, Dict, Any, Tuple
from config import (
    TIER_EASY_POINTS,
    TIER_MEDIUM_POINTS,
    TIER_HARD_POINTS,
    DEFAULT_OPEN_QUESTION_POINTS,
)

def calculate_tertile_distribution(
    closed_questions: List[Dict[str, Any]], correct_counts: Dict[int, int]
) -> Dict[int, Tuple[str, float]]:
    """
    Divides closed questions into three tertiles based on correct answer count:
    - Top 1/3 (highest accuracy / easiest) -> 1.1 points ('easy')
    - Middle 1/3 (medium accuracy) -> 1.7 points ('medium')
    - Bottom 1/3 (lowest accuracy / hardest) -> 2.5 points ('hard')
    Returns: {question_id: (tier_name, points)}
    """
    total_closed = len(closed_questions)
    if total_closed == 0:
        return {}

    # Sort closed questions by correct_count descending (highest correct count first)
    # Tie-break by question_num ascending
    sorted_q = sorted(
        closed_questions,
        key=lambda q: (correct_counts.get(q["id"], 0), -q["question_num"]),
        reverse=True,
    )

    if total_closed == 1:
        # Single question defaults to medium
        return {sorted_q[0]["id"]: ("medium", TIER_MEDIUM_POINTS)}

    if total_closed == 2:
        # 2 questions: one easy, one hard
        return {
            sorted_q[0]["id"]: ("easy", TIER_EASY_POINTS),
            sorted_q[1]["id"]: ("hard", TIER_HARD_POINTS),
        }

    # Standard 3-way split
    base_size = total_closed // 3
    remainder = total_closed % 3

    # Distribute remainder evenly: middle or easy/medium get extra
    easy_count = base_size + (1 if remainder >= 1 else 0)
    medium_count = base_size + (1 if remainder == 2 else 0)
    hard_count = total_closed - easy_count - medium_count

    result: Dict[int, Tuple[str, float]] = {}

    for idx, q in enumerate(sorted_q):
        q_id = q["id"]
        if idx < easy_count:
            result[q_id] = ("easy", TIER_EASY_POINTS)
        elif idx < easy_count + medium_count:
            result[q_id] = ("medium", TIER_MEDIUM_POINTS)
        else:
            result[q_id] = ("hard", TIER_HARD_POINTS)

    return result


async def run_test_analytics_and_scoring(test_id: int, *, finish=False, owner_id=None) -> Dict[str, Any]:
    """Read, score and optionally close one consistent SQLite snapshot."""
    from scripts.database.db import get_db_connection
    from services.platform_service import PlatformError, one, rows, require_owner

    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        test = await one(db, "SELECT * FROM tests WHERE id = ?", (test_id,))
        if not test:
            raise PlatformError("Test topilmadi.", 404)
        if owner_id is not None:
            require_owner(test, owner_id)
        questions = await rows(db, "SELECT * FROM questions WHERE test_id = ? ORDER BY question_num", (test_id,))
        submissions = await rows(db, "SELECT * FROM submissions WHERE test_id = ? ORDER BY submitted_at, id", (test_id,))
        all_answers = await rows(db, "SELECT a.* FROM answers a JOIN submissions s ON s.id = a.submission_id WHERE s.test_id = ?", (test_id,))
        if any(a["grading_status"] != "done" for a in all_answers):
            raise PlatformError("Ochiq javoblar hali tekshirilmoqda. Kuting yoki qo'lda baholang.", 409)
        if len(all_answers) != len(submissions) * len(questions):
            raise PlatformError("Ayrim topshiriqlar to'liq saqlanmagan; avval ularni tekshiring.", 409)
        correct_counts = {q["id"]: 0 for q in questions}
        for answer in all_answers:
            correct_counts[answer["question_id"]] += int(answer["is_correct"] == 1)
        closed = [q for q in questions if q["question_type"] == "closed"]
        opened = [q for q in questions if q["question_type"] == "open"]
        distribution = calculate_tertile_distribution(closed, correct_counts)
        points = {qid: item[1] for qid, item in distribution.items()}
        points.update({q["id"]: q["assigned_points"] or DEFAULT_OPEN_QUESTION_POINTS for q in opened})
        summary = {"total_participants": len(submissions), "total_questions": len(questions),
                   "closed_count": len(closed), "open_count": len(opened),
                   "tier_distribution": distribution, "question_points": points}
        if test["status"] == "finished":
            return summary
        if test["status"] != "active":
            raise PlatformError("Test faol emas.", 409)
        await db.executemany(
            "UPDATE questions SET correct_count = ?, assigned_tier = ?, assigned_points = ? WHERE id = ?",
            [(correct_counts[q["id"]], distribution[q["id"]][0] if q["question_type"] == "closed" else "open", points[q["id"]], q["id"]) for q in questions],
        )
        totals = {s["id"]: [0, 0.0] for s in submissions}
        answer_updates = []
        for answer in all_answers:
            earned = points[answer["question_id"]] if answer["is_correct"] == 1 else 0.0
            totals[answer["submission_id"]][0] += int(answer["is_correct"] == 1)
            totals[answer["submission_id"]][1] += earned
            answer_updates.append((earned, answer["id"]))
        await db.executemany("UPDATE answers SET points_awarded = ? WHERE id = ?", answer_updates)
        ranked = sorted(submissions, key=lambda s: (-round(totals[s["id"]][1], 2), -totals[s["id"]][0], s["id"]))
        await db.executemany("UPDATE submissions SET total_correct = ?, total_score = ?, rank = ? WHERE id = ?",
                             [(totals[s["id"]][0], round(totals[s["id"]][1], 2), rank, s["id"]) for rank, s in enumerate(ranked, 1)])
        if finish:
            await db.execute("UPDATE tests SET status = 'finished', finished_at = CURRENT_TIMESTAMP WHERE id = ?", (test_id,))
            await db.executemany("INSERT OR IGNORE INTO jobs(kind, target) VALUES ('notify', ?)", [(f"final:{s['id']}",) for s in submissions])
        await db.commit()
        return summary
