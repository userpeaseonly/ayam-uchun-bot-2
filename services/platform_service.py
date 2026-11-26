"""Transactional Mini App operations shared with the Telegram handlers."""

import json
import uuid

from scripts.database.db import get_db_connection
from services.test_document import TestDocument, normalize_answer, student_document


UNSET = object()


class PlatformError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


async def one(db, sql, args=()):
    cursor = await db.execute(sql, args)
    row = await cursor.fetchone()
    return dict(row) if row else None


async def rows(db, sql, args=()):
    cursor = await db.execute(sql, args)
    return [dict(row) for row in await cursor.fetchall()]


def require_owner(record, owner_id):
    if not record or record.get("owner_id", record.get("created_by")) != owner_id:
        raise PlatformError("Topilmadi yoki ruxsat yo'q.", 404)


async def create_import(owner_id, title, assets):
    import_id = uuid.uuid4().hex
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        from services.upload_service import enforce_import_limit
        await enforce_import_limit(db, owner_id)
        await db.execute("INSERT INTO imports(id, owner_id, title) VALUES (?, ?, ?)",
                         (import_id, owner_id, title[:300] or "Yangi test"))
        await db.executemany(
            "INSERT INTO assets(id, import_id, kind, filename, mime, original_name, source_size) VALUES (?, ?, 'source', ?, ?, ?, ?)",
            [(a["id"], import_id, a["filename"], a["mime"], a["original_name"], a.get("source_size", 0)) for a in assets],
        )
        await db.execute("INSERT INTO jobs(kind, target) VALUES ('import', ?)", (import_id,))
        await db.commit()
    return import_id


async def get_import(import_id, owner_id):
    async with get_db_connection() as db:
        record = await one(db, "SELECT * FROM imports WHERE id = ?", (import_id,))
        require_owner(record, owner_id)
        record["document"] = json.loads(record.pop("document_json")) if record["document_json"] else None
        record["assets"] = await rows(db, "SELECT id, kind, page, original_name FROM assets WHERE import_id = ? ORDER BY page", (import_id,))
        return record


async def list_imports(owner_id):
    async with get_db_connection() as db:
        return await rows(db, "SELECT id, title, status, progress, error, published_test_id FROM imports WHERE owner_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 100", (owner_id,))


async def retry_import(import_id, owner_id):
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        record = await one(db, "SELECT * FROM imports WHERE id = ?", (import_id,))
        require_owner(record, owner_id)
        if record["status"] != "failed":
            raise PlatformError("Faqat xatolik bilan tugagan importni qayta boshlash mumkin.", 409)
        await db.execute("UPDATE jobs SET status = 'queued', attempts = 0, available_at = 0, error = NULL WHERE kind = 'import' AND target = ?", (import_id,))
        await db.execute("UPDATE imports SET status = 'queued', error = NULL WHERE id = ?", (import_id,))
        await db.commit()


async def save_import(import_id, owner_id, document, revision, visibility=None, subject=None, duration_minutes=UNSET):
    parsed = TestDocument.model_validate(document)
    # A teacher's valid saved answer/rubric is the review action. Do not trust a
    # client checkbox, and never approve incomplete content or AI imports here.
    passage_ids = {passage.id for passage in parsed.passages}
    for question in parsed.questions:
        question.reviewed = not question.readiness_errors(passage_ids)
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        record = await one(db, "SELECT * FROM imports WHERE id = ?", (import_id,))
        require_owner(record, owner_id)
        if record["status"] != "review" or record["revision"] != revision:
            raise PlatformError("Qoralama o'zgargan yoki tahrirlash uchun tayyor emas. Yangilang.", 409)
        from services.explanation_service import validate_references
        await validate_references(db, import_id, parsed)
        from services.catalog_service import publication_metadata
        visibility, subject = publication_metadata(visibility if visibility is not None else record["visibility"],
                                                  subject if subject is not None else record["subject"])
        from services.timer_service import validate_duration
        duration = validate_duration(record["duration_minutes"] if duration_minutes is UNSET else duration_minutes)
        await db.execute("UPDATE imports SET title = ?, document_json = ?, visibility = ?, subject = ?, duration_minutes = ?, revision = revision + 1 WHERE id = ?",
                         (parsed.title, parsed.model_dump_json(), visibility, subject, duration, import_id))
        await db.commit()
    return revision + 1


async def publish_import(import_id, owner_id, revision):
    # Generate files outside the write transaction; publication then rechecks revision.
    record = await get_import(import_id, owner_id)
    if record["published_test_id"]:
        return record["published_test_id"]
    if record["status"] != "review" or revision != record["revision"]:
        raise PlatformError("Qoralamani saqlang va yangilang.", 409)
    document = TestDocument.model_validate(record["document"])
    errors = document.publication_errors()
    if errors:
        raise PlatformError("\n".join(errors))
    from services.import_service import materialize_media
    await materialize_media(import_id, document)
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        current = await one(db, "SELECT * FROM imports WHERE id = ?", (import_id,))
        require_owner(current, owner_id)
        if current["published_test_id"]:
            return current["published_test_id"]
        if current["status"] != "review" or current["revision"] != revision:
            raise PlatformError("Qoralama o'zgargan. Yangilang.", 409)
        from services.explanation_service import validate_references
        await validate_references(db, import_id, document)
        from services.catalog_service import publisher_name, create_session
        name = await publisher_name(db, owner_id)
        serialized = document.model_dump_json()
        cursor = await db.execute("INSERT INTO test_templates(owner_id, title, document_json, source_import_id) VALUES (?, ?, ?, ?)",
                                  (owner_id, document.title, serialized, import_id))
        template = {"id": cursor.lastrowid, "document_json": serialized, "source_import_id": import_id}
        test_id = await create_session(db, owner_id, template, name, current["visibility"], current["subject"], current["duration_minutes"])
        await db.execute("UPDATE imports SET status = 'published', published_test_id = ?, document_json = ? WHERE id = ?", (test_id, document.model_dump_json(), import_id))
        await db.commit()
    return test_id


async def load_test(code):
    async with get_db_connection() as db:
        test = await one(db, "SELECT * FROM tests WHERE code = ? OR public_id = ?", (code.strip().upper(), code.strip().lower()))
    if not test:
        raise PlatformError("Test topilmadi.", 404)
    return test


async def test_for_student(code, user_id):
    test = await load_test(code)
    if not test["document_json"]:
        raise PlatformError("Bu test bot orqali topshiriladi; savol matnlari yuklanmagan.")
    if test["status"] not in ("active", "finished"):
        raise PlatformError("Test vaqtincha yopiq.", 409)
    async with get_db_connection() as db:
        from services.access_policy import require_access
        from services.timer_service import require_started, expire_if_due, timer_payload
        await db.execute("BEGIN IMMEDIATE")
        test = await one(db, "SELECT * FROM tests WHERE id = ?", (test["id"],))
        access = await require_access(db, test, user_id)
        attempt = await require_started(db, test, user_id)
        await expire_if_due(db, test, user_id)
        timer = timer_payload(attempt)
        draft = await one(db, "SELECT * FROM answer_drafts WHERE test_id = ? AND user_id = ?", (test["id"], user_id))
        await db.commit()
    result = {"timer": timer, "id": test["id"], "code": test["code"], "status": test["status"], "document": student_document(json.loads(test["document_json"])),
              "draft": json.loads(draft["answers_json"]) if draft else {}, "revision": draft["revision"] if draft else 0}
    from services.catalog_service import summary
    result.update(await summary(test["id"], user_id))
    result["access"] = access
    result["submission"] = await submission_result(test["id"], user_id)
    return result


def validate_answers(questions, answers, *, final=False):
    if not isinstance(answers, dict):
        raise PlatformError("Javoblar noto'g'ri formatda.")
    allowed = {str(q["question_num"]): q for q in questions}
    if set(answers) - set(allowed):
        raise PlatformError("Noma'lum savol raqami.")
    cleaned = {}
    for key, value in answers.items():
        q = allowed[key]
        content = json.loads(q["content_json"]) if q.get("content_json") else {}
        parts = content.get("parts", [])
        if parts:
            if not isinstance(value, dict) or set(value) - {p["id"] for p in parts}:
                raise PlatformError(f"{key}-savol qismlari noto'g'ri.")
            if any(not isinstance(v, str) or len(v) > 10000 for v in value.values()):
                raise PlatformError("Javob matni juda uzun yoki noto'g'ri.")
            cleaned[key] = {p["id"]: value.get(p["id"], "").strip() for p in parts}
        else:
            if not isinstance(value, str) or len(value) > 10000:
                raise PlatformError("Javob matni juda uzun yoki noto'g'ri.")
            value = value.strip()
            if q["question_type"] == "closed":
                value = value.upper()
                labels = [o["label"] for o in content.get("options", [])] or list("ABCDEF")
                if value and value not in labels:
                    raise PlatformError(f"{key}-savol varianti noto'g'ri.")
            cleaned[key] = value
    return cleaned


async def save_draft(test_id, user_id, answers, revision):
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        test = await one(db, "SELECT * FROM tests WHERE id = ?", (test_id,))
        from services.access_policy import require_access
        await require_access(db, test, user_id)
        if test["status"] != "active":
            raise PlatformError("Test yopilgan.", 409)
        from services.timer_service import require_started, expire_if_due
        await require_started(db, test, user_id)
        if await expire_if_due(db, test, user_id):
            await db.commit()
            raise PlatformError("Vaqt tugadi. Saqlangan javoblaringiz avtomatik topshirildi.", 409)
        if await one(db, "SELECT id FROM submissions WHERE test_id = ? AND user_id = ?", (test_id, user_id)):
            raise PlatformError("Javoblar allaqachon topshirilgan.", 409)
        questions = await rows(db, "SELECT * FROM questions WHERE test_id = ?", (test_id,))
        cleaned = validate_answers(questions, answers)
        existing = await one(db, "SELECT revision FROM answer_drafts WHERE test_id = ? AND user_id = ?", (test_id, user_id))
        if revision != (existing["revision"] if existing else 0):
            raise PlatformError("Javoblar boshqa oynada o'zgargan. Yangilang.", 409)
        await db.execute("INSERT INTO answer_drafts VALUES (?, ?, ?, ?) ON CONFLICT(test_id, user_id) DO UPDATE SET answers_json = excluded.answers_json, revision = excluded.revision",
                         (test_id, user_id, json.dumps(cleaned, ensure_ascii=False), revision + 1))
        await db.commit()
    return revision + 1


async def submit_answers(test_id, user, answers):
    """All answers and grading jobs commit together, before any network call."""
    user_id = user["id"]
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        test = await one(db, "SELECT * FROM tests WHERE id = ?", (test_id,))
        from services.access_policy import require_access
        await require_access(db, test, user_id)
        existing = await one(db, "SELECT id FROM submissions WHERE test_id = ? AND user_id = ?", (test_id, user_id))
        if existing:
            return existing["id"]  # Safe retry after lost HTTP response.
        if test["status"] != "active":
            raise PlatformError("Test yopilgan; yangi javoblar qabul qilinmaydi.", 409)
        from services.timer_service import require_started, expire_if_due
        await require_started(db, test, user_id)
        expired = await expire_if_due(db, test, user_id)
        sub_id = expired or await insert_submission(db, test, user, answers)
        await db.commit()
    return sub_id


async def insert_submission(db, test, user, answers, *, auto=False):
    """Shared atomic answer/grading writes for manual and deadline submissions."""
    test_id, user_id = test["id"], user["id"]
    questions = await rows(db, "SELECT * FROM questions WHERE test_id = ? ORDER BY question_num", (test_id,))
    cleaned = validate_answers(questions, answers, final=True)
    cursor = await db.execute("INSERT INTO submissions(test_id, user_id, first_name, last_name, username) VALUES (?, ?, ?, ?, ?)",
                              (test_id, user_id, user.get("first_name"), user.get("last_name"), user.get("username")))
    sub_id = cursor.lastrowid
    answer_rows = []
    for q in questions:
        value = cleaned.get(str(q["question_num"]), "")
        content = json.loads(q["content_json"]) if q["content_json"] else {}
        if isinstance(value, dict):
            text = "\n".join(f"{part['id']}) {value.get(part['id'], '')}" for part in content["parts"])
            blank = not any(value.values())
            incomplete = any(not value.get(part["id"]) for part in content["parts"])
        else:
            text, blank, incomplete = value, not value, False
        correct, status = 0, "done"
        if not blank and not incomplete:
            if q["question_type"] == "closed":
                correct = int(text.upper() == (q["correct_answer"] or "").upper())
            elif content.get("accepted_answers") and not content.get("parts"):
                correct = int(normalize_answer(text) in {normalize_answer(a) for a in content["accepted_answers"]})
                # A non-match can still qualify semantically when a rubric exists.
                if not correct and q["ai_instructions"]:
                    status = "pending"
            else:
                status = "pending"
        answer_rows.append((sub_id, q["id"], text, correct, status))
    await db.executemany("INSERT INTO answers(submission_id, question_id, user_answer, is_correct, grading_status) VALUES (?, ?, ?, ?, ?)", answer_rows)
    pending = await rows(db, "SELECT id FROM answers WHERE submission_id = ? AND grading_status = 'pending'", (sub_id,))
    await db.executemany("INSERT INTO jobs(kind, target) VALUES ('grade', ?)", [(str(a["id"]),) for a in pending])
    await db.execute("UPDATE submissions SET total_correct = (SELECT COUNT(*) FROM answers WHERE submission_id = ? AND is_correct = 1) WHERE id = ?", (sub_id, sub_id))
    await db.execute("DELETE FROM answer_drafts WHERE test_id = ? AND user_id = ?", (test_id, user_id))
    if auto:
        await db.execute("UPDATE submissions SET auto_submitted = 1 WHERE id = ?", (sub_id,))
    await db.execute("UPDATE jobs SET status = 'done' WHERE kind = 'expire' AND target = ?", (f"{test_id}:{user_id}",))
    return sub_id


async def submission_result(test_id, user_id):
    async with get_db_connection() as db:
        sub = await one(db, "SELECT * FROM submissions WHERE test_id = ? AND user_id = ?", (test_id, user_id))
        if not sub:
            return None
        test = await one(db, "SELECT * FROM tests WHERE id = ?", (test_id,))
        answers = await rows(db, "SELECT q.question_num AS number, q.content_json, a.is_correct, a.grading_status FROM answers a JOIN questions q ON q.id = a.question_id WHERE a.submission_id = ? ORDER BY q.question_num", (sub["id"],))
    result = {"id": sub["id"], "auto_submitted": bool(sub["auto_submitted"]), "answers": [{"number": a["number"], "status": a["grading_status"],
               "correct": bool(a["is_correct"]) if a["grading_status"] == "done" else None} for a in answers]}
    # Submission, including automatic expiry, unlocks only this session's audio.
    for answer, row in zip(result["answers"], answers):
        audio = json.loads(row["content_json"] or '{}').get('explanation_audio')
        if audio:
            answer['explanation_audio_url'] = f"/api/tests/{test['public_id']}/explanations/{audio}"
    if test["status"] == "finished":
        result.update(score=sub["total_score"], rank=sub["rank"], total_correct=sub["total_correct"])
    return result


async def teacher_results(test_id, owner_id):
    async with get_db_connection() as db:
        test = await one(db, "SELECT * FROM tests WHERE id = ?", (test_id,))
        require_owner(test, owner_id)
        test["active_attempts"] = (await one(db, """SELECT COUNT(*) AS n FROM timed_attempts a
            LEFT JOIN submissions s ON s.test_id = a.test_id AND s.user_id = a.user_id
            WHERE a.test_id = ? AND a.deadline_at IS NOT NULL AND s.id IS NULL""", (test_id,)))["n"]
        submissions = await rows(db, "SELECT * FROM submissions WHERE test_id = ? ORDER BY rank IS NULL, rank, submitted_at, id", (test_id,))
        answers = await rows(db, "SELECT a.*, q.question_num FROM answers a JOIN questions q ON q.id = a.question_id WHERE q.test_id = ? ORDER BY a.submission_id, q.question_num", (test_id,))
        questions = await rows(db, "SELECT * FROM questions WHERE test_id = ? ORDER BY question_num", (test_id,))
    test.pop("document_json", None)
    from services.catalog_service import summary
    test.update(await summary(test_id, owner_id))
    return {"test": test, "submissions": submissions, "answers": answers, "questions": questions}


async def override_answer(test_id, owner_id, answer_id, correct, feedback):
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        test = await one(db, "SELECT * FROM tests WHERE id = ?", (test_id,))
        require_owner(test, owner_id)
        if test["status"] != "active":
            raise PlatformError("Yakunlangan test baholarini o'zgartirib bo'lmaydi.", 409)
        answer = await one(db, "SELECT a.* FROM answers a JOIN questions q ON q.id = a.question_id WHERE a.id = ? AND q.test_id = ?", (answer_id, test_id))
        if not answer:
            raise PlatformError("Javob topilmadi.", 404)
        await db.execute("UPDATE answers SET is_correct = ?, grading_status = 'done', ai_feedback = ? WHERE id = ?", (int(correct), feedback[:2000], answer_id))
        await db.execute("UPDATE jobs SET status = 'done' WHERE kind = 'grade' AND target = ?", (str(answer_id),))
        await db.execute("UPDATE submissions SET total_correct = (SELECT COUNT(*) FROM answers WHERE submission_id = ? AND is_correct = 1) WHERE id = ?", (answer["submission_id"], answer["submission_id"]))
        await db.commit()


async def retry_grading(test_id, owner_id):
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        test = await one(db, "SELECT * FROM tests WHERE id = ?", (test_id,))
        require_owner(test, owner_id)
        if test["status"] != "active":
            raise PlatformError("Test yopilgan.", 409)
        await db.execute("UPDATE jobs SET status = 'queued', attempts = 0, available_at = 0 WHERE kind = 'grade' AND target IN (SELECT CAST(a.id AS TEXT) FROM answers a JOIN questions q ON q.id = a.question_id WHERE q.test_id = ? AND a.grading_status = 'pending') AND status = 'failed'", (test_id,))
        await db.commit()
