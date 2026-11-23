"""Durable, bounded background processing for a single application instance."""

import asyncio
import html
import logging
import time

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from scripts.database.db import get_db_connection
from services.ai_service import ai_evaluator
from services.import_service import process_import
from services.platform_service import one

logger = logging.getLogger(__name__)


async def recover_jobs():
    # Deployment runs one application instance; no second polling/worker replica.
    async with get_db_connection() as db:
        await db.execute("UPDATE jobs SET status = 'queued' WHERE status = 'running'")
        await db.commit()


async def claim_job(*, imports=False, timers=False):
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        job = await one(db, "SELECT * FROM jobs WHERE status = 'queued' AND available_at <= ? AND "
                            + ("kind = 'import'" if imports else "kind = 'expire'" if timers else "kind NOT IN ('import', 'expire')") + " ORDER BY id LIMIT 1", (time.time(),))
        if job:
            await db.execute("UPDATE jobs SET status = 'running', attempts = attempts + 1 WHERE id = ?", (job["id"],))
            job["attempts"] += 1
        await db.commit()
    return job


async def grade_answer(answer_id):
    async with get_db_connection() as db:
        answer = await one(db, "SELECT a.*, q.question_num, q.ai_instructions, q.content_json, t.document_json FROM answers a JOIN questions q ON q.id = a.question_id JOIN tests t ON t.id = q.test_id WHERE a.id = ?", (answer_id,))
    if not answer or answer["grading_status"] == "done":
        return
    import json
    content = json.loads(answer["content_json"]) if answer["content_json"] else {}
    rubric = answer["ai_instructions"] or ""
    if content:
        rubric = "Savol: " + content["text"] + "\nQismlar: " + json.dumps(content.get("parts", []), ensure_ascii=False) + "\nO'qituvchi mezoni: " + rubric
        if content.get("passage_id") and answer["document_json"]:
            document = json.loads(answer["document_json"])
            passage = next((p for p in document["passages"] if p["id"] == content["passage_id"]), None)
            if passage:
                rubric += "\nSavol uchun umumiy matn: " + passage["text"]
    correct, explanation = await ai_evaluator.evaluate_open_answer(answer["question_num"], rubric, answer["user_answer"])
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        # A teacher override during the network call takes precedence.
        await db.execute("UPDATE answers SET is_correct = ?, ai_feedback = ?, grading_status = 'done' WHERE id = ? AND grading_status = 'pending'", (int(correct), explanation, answer_id))
        await db.execute("UPDATE submissions SET total_correct = (SELECT COUNT(*) FROM answers WHERE submission_id = ? AND is_correct = 1) WHERE id = ?", (answer["submission_id"], answer["submission_id"]))
        await db.commit()


async def notify(target, bot):
    if bot is None:
        return
    kind, sub_id = target.split(":", 1)
    if kind in ("import", "import_failed"):
        async with get_db_connection() as db:
            imported = await one(db, "SELECT * FROM imports WHERE id = ?", (sub_id,))
        if not imported or (kind == "import_failed" and imported["status"] != "failed"):
            return
        from keyboards.inline import get_mini_app_keyboard
        if kind == "import":
            text = f"✅ <b>{html.escape(imported['title'])}</b>\nSavollar ajratildi. Mini App'da tekshiring, javoblarni kiriting va tasdiqlang."
        else:
            text = "⚠️ Testni ajratib bo'lmadi. Mini App'da importni ochib, xatoni tekshiring va qayta urinib ko'ring."
        try:
            await bot.send_message(imported["owner_id"], text, parse_mode="HTML", reply_markup=get_mini_app_keyboard(import_id=sub_id))
        except TelegramForbiddenError:
            pass
        return
    async with get_db_connection() as db:
        sub = await one(db, "SELECT s.*, t.code, t.title, t.status FROM submissions s JOIN tests t ON t.id = s.test_id WHERE s.id = ?", (sub_id,))
    if not sub:
        return
    if kind == "final":
        text = (f"🏁 <b>{html.escape(sub['code'])}: {html.escape(sub['title'])}</b>\n"
                f"✅ To'g'ri javoblar: {sub['total_correct']}\n"
                f"⭐ Ball: {sub['total_score']}\n🏆 O'rin: {sub['rank']}")
    else:
        from services.platform_service import submission_result
        result = await submission_result(sub["test_id"], sub["user_id"])
        lines = [f"{a['number']}. " + ("⏳ Tekshirilmoqda" if a["correct"] is None else "✅" if a["correct"] else "❌") for a in result["answers"]]
        text = f"✅ <b>{html.escape(sub['code'])}: javoblaringiz qabul qilindi.</b>\n" + "\n".join(lines) + "\nBall va o'rin test yakunlangach e'lon qilinadi."
    try:
        await bot.send_message(sub["user_id"], text, parse_mode="HTML")
    except TelegramForbiddenError:
        # A student who blocked the bot must not block grading/finalization.
        return


async def execute_job(job, bot=None):
    try:
        if job["kind"] == "import":
            await process_import(job["target"])
        elif job["kind"] == "expire":
            from services.timer_service import expire_attempt
            test_id, user_id = map(int, job["target"].split(":"))
            retry_at = await expire_attempt(test_id, user_id)
            if retry_at is not None:
                # Clock adjustment between claiming and executing must not lose expiry.
                async with get_db_connection() as db:
                    await db.execute("UPDATE jobs SET status = 'queued', available_at = ? WHERE id = ?", (retry_at, job["id"]))
                    await db.commit()
                return
        elif job["kind"] == "grade":
            await grade_answer(int(job["target"]))
        elif job["kind"] == "notify":
            await notify(job["target"], bot)
        async with get_db_connection() as db:
            await db.execute("UPDATE jobs SET status = 'done', error = NULL WHERE id = ?", (job["id"],))
            if job["kind"] == "grade":
                answer = await one(db, "SELECT submission_id FROM answers WHERE id = ?", (job["target"],))
                if answer and not await one(db, "SELECT id FROM answers WHERE submission_id = ? AND grading_status != 'done' LIMIT 1", (answer["submission_id"],)):
                    await db.execute("INSERT OR IGNORE INTO jobs(kind, target) VALUES ('notify', ?)", (f"feedback:{answer['submission_id']}",))
            await db.commit()
    except asyncio.CancelledError:
        raise  # Startup recovers the claimed job.
    except Exception as error:
        from services.deepseek_client import AIUnavailable
        from services.platform_service import PlatformError
        message = str(error)[:500] if isinstance(error, (AIUnavailable, PlatformError)) else "Amal bajarilmadi. Qayta urinib ko'ring yoki administratorga murojaat qiling."
        logger.warning("Job %s (%s) failed: %s", job["id"], job["kind"], type(error).__name__)
        rate_limited = isinstance(error, TelegramRetryAfter)
        failed = job["attempts"] >= 3 and not rate_limited
        delay = error.retry_after + 1 if rate_limited else min(300, 10 ** job["attempts"])
        async with get_db_connection() as db:
            await db.execute("UPDATE jobs SET status = ?, error = ?, available_at = ? WHERE id = ? AND status != 'done'",
                             ("failed" if failed else "queued", message, time.time() + delay, job["id"]))
            if job["kind"] == "import":
                await db.execute("UPDATE imports SET status = ?, error = ? WHERE id = ?", ("failed" if failed else "queued", message, job["target"]))
                if failed:
                    await db.execute("INSERT OR IGNORE INTO jobs(kind, target) SELECT 'notify', ? WHERE EXISTS (SELECT 1 FROM telegram_uploads WHERE import_id = ?)", (f"import_failed:{job['target']}", job["target"]))
            await db.commit()


async def worker_loop(bot=None, *, imports=False, timers=False):
    while True:
        try:
            job = await claim_job(imports=imports, timers=timers)
            if job:
                await execute_job(job, bot)
            else:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Background worker iteration failed")
            await asyncio.sleep(3)
