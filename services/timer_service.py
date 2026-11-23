"""Persistent server deadlines. No browser clock or in-memory task grants time."""

import json
import time

from scripts.database.db import get_db_connection
from services.platform_service import PlatformError, one, rows, require_owner, UNSET


def current_time():
    return time.time()


def validate_duration(value):
    if value is not None and (type(value) is not int or not 1 <= value <= 1440):
        raise PlatformError("Vaqt chegarasi 1–1440 oralig‘ida butun daqiqa bo‘lishi kerak.")
    return value


def timer_payload(attempt, *, now=None):
    if not attempt or attempt["deadline_at"] is None:
        return None
    return {"started_at": attempt["started_at"], "deadline_at": attempt["deadline_at"],
            "server_now": current_time() if now is None else now}


async def require_started(db, test, user_id):
    if not test["duration_minutes"]:
        return None
    attempt = await one(db, "SELECT * FROM timed_attempts WHERE test_id = ? AND user_id = ?", (test["id"], user_id))
    if not attempt and not await one(db, "SELECT id FROM submissions WHERE test_id = ? AND user_id = ?", (test["id"], user_id)):
        raise PlatformError("Avval testni boshlang. Vaqt shundan so‘ng hisoblanadi.", 409)
    return attempt


async def start_attempt(test_id, user):
    from services.access_policy import require_access
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        test = await one(db, "SELECT * FROM tests WHERE id = ?", (test_id,))
        await require_access(db, test, user["id"])
        if await one(db, "SELECT id FROM submissions WHERE test_id = ? AND user_id = ?", (test_id, user["id"])):
            return
        if test["status"] != "active":
            raise PlatformError("Test yakunlangan.", 409)
        now = current_time()
        deadline = now + test["duration_minutes"] * 60 if test["duration_minutes"] else None
        await db.execute("""INSERT OR IGNORE INTO timed_attempts
            (test_id, user_id, started_at, deadline_at, first_name, last_name, username)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (test_id, user["id"], now, deadline, user.get("first_name"), user.get("last_name"), user.get("username")))
        if test["duration_minutes"]:
            attempt = await require_started(db, test, user["id"])
            await db.execute("INSERT OR IGNORE INTO jobs(kind, target, available_at) VALUES ('expire', ?, ?)",
                             (f"{test_id}:{user['id']}", attempt["deadline_at"]))
            await expire_if_due(db, test, user["id"])
        await db.commit()


async def expire_if_due(db, test, user_id):
    """Caller owns the write transaction. Late request bodies are never accepted."""
    from services.platform_service import insert_submission
    attempt = await one(db, "SELECT * FROM timed_attempts WHERE test_id = ? AND user_id = ?", (test["id"], user_id))
    if not attempt or attempt["deadline_at"] is None or current_time() < attempt["deadline_at"]:
        return None
    existing = await one(db, "SELECT id FROM submissions WHERE test_id = ? AND user_id = ?", (test["id"], user_id))
    if existing:
        return existing["id"]
    if test["status"] != "active":
        return None
    draft = await one(db, "SELECT answers_json FROM answer_drafts WHERE test_id = ? AND user_id = ?", (test["id"], user_id))
    user = {"id": user_id, **{key: attempt[key] for key in ("first_name", "last_name", "username")}}
    sub_id = await insert_submission(db, test, user, json.loads(draft["answers_json"]) if draft else {}, auto=True)
    await db.execute("INSERT OR IGNORE INTO jobs(kind, target) VALUES ('notify', ?)", (f"feedback:{sub_id}",))
    return sub_id


async def expire_attempt(test_id, user_id):
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        test = await one(db, "SELECT * FROM tests WHERE id = ?", (test_id,))
        retry_at = None
        if test:
            attempt = await one(db, "SELECT deadline_at FROM timed_attempts WHERE test_id = ? AND user_id = ?", (test_id, user_id))
            if attempt and attempt["deadline_at"] is not None and current_time() < attempt["deadline_at"]:
                retry_at = attempt["deadline_at"]
            else:
                await expire_if_due(db, test, user_id)
        await db.commit()
    return retry_at


async def settle_test_deadlines(test_id, owner_id=None):
    """Settle expired attempts before the teacher tries to finalize the cohort."""
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        test = await one(db, "SELECT * FROM tests WHERE id = ?", (test_id,))
        if owner_id is not None:
            require_owner(test, owner_id)
        if test and test["status"] == "active":
            due = await rows(db, """SELECT a.user_id FROM timed_attempts a LEFT JOIN submissions s
                ON s.test_id = a.test_id AND s.user_id = a.user_id
                WHERE a.test_id = ? AND a.deadline_at <= ? AND s.id IS NULL""", (test_id, current_time()))
            for attempt in due:
                await expire_if_due(db, test, attempt["user_id"])
        await db.commit()


async def attempt_status(test_id, user_id):
    from services.access_policy import require_access
    from services.platform_service import submission_result
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        test = await one(db, "SELECT * FROM tests WHERE id = ?", (test_id,))
        await require_access(db, test, user_id)
        attempt = await require_started(db, test, user_id)
        await expire_if_due(db, test, user_id)
        timer = timer_payload(attempt)
        await db.commit()
    return {"timer": timer, "submission": await submission_result(test_id, user_id)}
