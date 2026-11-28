from typing import List, Dict, Any, Tuple
from config import (
    TIER_EASY_POINTS,
    TIER_MEDIUM_POINTS,
    TIER_HARD_POINTS,
    DEFAULT_OPEN_QUESTION_POINTS,
)


async def _score_rasch(db, test_id, questions, submissions, answers):
    import asyncio
    import hashlib
    import json
    from datetime import datetime, timezone
    from services.rasch import calibrate

    by_submission = {s["id"]: {} for s in submissions}
    for answer in answers:
        by_submission[answer["submission_id"]][answer["question_id"]] = int(answer["is_correct"] == 1)
    matrix = [[by_submission[s["id"]][q["id"]] for q in questions] for s in submissions]
    # Keep Telegram/API event handling responsive during numerical estimation.
    # The transaction fixes the cohort and settled grades throughout scoring.
    snapshot = await asyncio.to_thread(calibrate, matrix, item_count=len(questions))
    snapshot["created_at"] = datetime.now(timezone.utc).isoformat()
    snapshot["response_digest"] = hashlib.sha256(json.dumps(matrix, separators=(',', ':')).encode()).hexdigest()
    for item, question in zip(snapshot["items"], questions):
        item["question_id"] = question["id"]
    for person, submission in zip(snapshot["persons"], submissions):
        person["submission_id"] = submission["id"]
    ordered = sorted(snapshot["persons"], key=lambda p: -p["raw"])
    ranks = {}
    for index, person in enumerate(ordered, 1):
        ranks.setdefault(person["raw"], index)
    await db.executemany("""UPDATE questions SET correct_count = ?, assigned_tier = 'rasch',
        assigned_points = NULL, difficulty_logit = ?, infit = ? WHERE id = ?""",
        [(item["correct"], item["difficulty"], item["infit"], item["question_id"])
         for item in snapshot["items"]])
    # A T-score is not additive. Do not pretend it awards per-answer points.
    await db.executemany("UPDATE answers SET points_awarded = NULL WHERE id = ?", [(a["id"],) for a in answers])
    await db.executemany("""UPDATE submissions SET total_correct = ?, total_score = ?, rank = ?,
        rasch_theta = ?, rasch_se = ? WHERE id = ?""",
        [(p["raw"], round(p["score"], 2) if p["score"] is not None else None,
          ranks[p["raw"]] if p["score"] is not None else None, p["theta"], p["se"], p["submission_id"])
         for p in snapshot["persons"]])
    await db.execute("UPDATE tests SET scoring_json = ? WHERE id = ?",
                     (json.dumps(snapshot, allow_nan=False, separators=(',', ':')), test_id))
    return snapshot

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

    if finish:
        from services.timer_service import settle_test_deadlines
        await settle_test_deadlines(test_id, owner_id)
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        test = await one(db, "SELECT * FROM tests WHERE id = ?", (test_id,))
        if not test:
            raise PlatformError("Test topilmadi.", 404)
        if owner_id is not None:
            require_owner(test, owner_id)
        if finish and await one(db, """SELECT a.user_id FROM timed_attempts a LEFT JOIN submissions s
                ON s.test_id = a.test_id AND s.user_id = a.user_id
                WHERE a.test_id = ? AND a.deadline_at IS NOT NULL AND s.id IS NULL LIMIT 1""", (test_id,)):
            raise PlatformError("O‘quvchilar testni ishlamoqda. Ular topshirishini yoki vaqt tugashini kuting.", 409)
        questions = await rows(db, "SELECT * FROM questions WHERE test_id = ? ORDER BY question_num", (test_id,))
        submissions = await rows(db, "SELECT * FROM submissions WHERE test_id = ? ORDER BY submitted_at, id", (test_id,))
        summary = {"total_participants": len(submissions), "total_questions": len(questions),
                   "closed_count": sum(q["question_type"] == "closed" for q in questions),
                   "open_count": sum(q["question_type"] == "open" for q in questions),
                   "scoring_method": test["scoring_method"]}
        if test["status"] == "finished":
            # Return persisted metadata. Repeated finalization must not even
            # recalibrate with a newer estimator or different settings.
            summary.update(tier_distribution={q["id"]: (q["assigned_tier"], q["assigned_points"])
                                               for q in questions if q["question_type"] == "closed"},
                           question_points={q["id"]: q["assigned_points"] for q in questions})
            return summary
        if test["status"] != "active":
            raise PlatformError("Test faol emas.", 409)
        all_answers = await rows(db, "SELECT a.* FROM answers a JOIN submissions s ON s.id = a.submission_id WHERE s.test_id = ?", (test_id,))
        if any(a["grading_status"] != "done" for a in all_answers):
            raise PlatformError("Ochiq javoblar hali tekshirilmoqda. Kuting yoki qo'lda baholang.", 409)
        if len(all_answers) != len(submissions) * len(questions):
            raise PlatformError("Ayrim topshiriqlar to'liq saqlanmagan; avval ularni tekshiring.", 409)
        if test["scoring_method"] == "rasch_v1":
            snapshot = await _score_rasch(db, test_id, questions, submissions, all_answers)
            summary.update(tier_distribution={}, question_points={}, scoring_status=snapshot["status"])
            if finish:
                await db.execute("UPDATE tests SET status = 'finished', finished_at = CURRENT_TIMESTAMP WHERE id = ?", (test_id,))
                await db.executemany("INSERT OR IGNORE INTO jobs(kind, target) VALUES ('notify', ?)", [(f"final:{s['id']}",) for s in submissions])
            await db.commit()
            return summary
        correct_counts = {q["id"]: 0 for q in questions}
        for answer in all_answers:
            correct_counts[answer["question_id"]] += int(answer["is_correct"] == 1)
        closed = [q for q in questions if q["question_type"] == "closed"]
        opened = [q for q in questions if q["question_type"] == "open"]
        distribution = calculate_tertile_distribution(closed, correct_counts)
        points = {qid: item[1] for qid, item in distribution.items()}
        points.update({q["id"]: q["assigned_points"] or DEFAULT_OPEN_QUESTION_POINTS for q in opened})
        summary.update(tier_distribution=distribution, question_points=points)
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
