from typing import List, Dict, Any, Tuple
import math
from config import (
    TIER_EASY_POINTS,
    TIER_MEDIUM_POINTS,
    TIER_HARD_POINTS,
    DEFAULT_OPEN_QUESTION_POINTS,
)
from scripts.database.models import (
    get_questions_for_test,
    get_submissions_for_test,
    get_all_answers_for_test,
    batch_update_question_stats,
    batch_update_answer_points,
    batch_update_submission_scores,
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


async def run_test_analytics_and_scoring(test_id: int) -> Dict[str, Any]:
    """
    Calculates dynamic points for all closed questions in the test,
    awards points to students, calculates ranks, and saves to database.
    Returns summary dictionary.
    """
    questions = await get_questions_for_test(test_id)
    submissions = await get_submissions_for_test(test_id)
    all_answers = await get_all_answers_for_test(test_id)

    # Map question_id -> question record
    q_map = {q["id"]: q for q in questions}

    # Count correct answers per question
    correct_counts: Dict[int, int] = {q["id"]: 0 for q in questions}
    for ans in all_answers:
        if ans["is_correct"] == 1:
            q_id = ans["question_id"]
            correct_counts[q_id] = correct_counts.get(q_id, 0) + 1

    # Separate closed and open questions
    closed_questions = [q for q in questions if q["question_type"] == "closed"]
    open_questions = [q for q in questions if q["question_type"] == "open"]

    # Calculate tertile distribution for closed questions
    closed_distribution = calculate_tertile_distribution(closed_questions, correct_counts)

    # Update question assigned_tier and assigned_points in database
    question_points: Dict[int, float] = {}
    q_updates: List[Tuple[int, str, float, int]] = []

    for q in closed_questions:
        q_id = q["id"]
        tier, pts = closed_distribution[q_id]
        question_points[q_id] = pts
        q_updates.append((correct_counts[q_id], tier, pts, q_id))

    for q in open_questions:
        q_id = q["id"]
        pts = q["assigned_points"] or DEFAULT_OPEN_QUESTION_POINTS
        question_points[q_id] = pts
        q_updates.append((correct_counts[q_id], "open", pts, q_id))

    await batch_update_question_stats(q_updates)

    # Calculate student points
    submission_totals: Dict[int, Dict[str, Any]] = {
        sub["id"]: {"total_correct": 0, "total_score": 0.0}
        for sub in submissions
    }

    # Update each answer with its awarded points
    ans_updates: List[Tuple[float, int]] = []
    for ans in all_answers:
        sub_id = ans["submission_id"]
        q_id = ans["question_id"]
        pts_earned = 0.0

        if ans["is_correct"] == 1:
            pts_earned = question_points.get(q_id, 0.0)
            if sub_id in submission_totals:
                submission_totals[sub_id]["total_correct"] += 1
                submission_totals[sub_id]["total_score"] += pts_earned

        ans_updates.append((pts_earned, ans["id"]))

    await batch_update_answer_points(ans_updates)

    # Sort submissions by score descending, then correct count descending
    ranked_submissions = sorted(
        submissions,
        key=lambda s: (
            submission_totals[s["id"]]["total_score"],
            submission_totals[s["id"]]["total_correct"],
        ),
        reverse=True,
    )

    # Assign ranks and save to DB
    sub_updates: List[Tuple[int, float, int, int]] = []
    for rank_idx, sub in enumerate(ranked_submissions, start=1):
        sub_id = sub["id"]
        stats = submission_totals[sub_id]
        rounded_score = round(stats["total_score"], 2)
        sub_updates.append((stats["total_correct"], rounded_score, rank_idx, sub_id))

    await batch_update_submission_scores(sub_updates)

    return {
        "total_participants": len(submissions),
        "total_questions": len(questions),
        "closed_count": len(closed_questions),
        "open_count": len(open_questions),
        "tier_distribution": closed_distribution,
        "question_points": question_points,
    }
