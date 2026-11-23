"""Public discovery, publisher profiles and independent assessment sessions."""

import secrets
import uuid
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

import config
from scripts.database.db import get_db_connection
from services.platform_service import PlatformError, one, rows, require_owner
from services.test_document import TestDocument


SUMMARY_SQL = """SELECT t.id, t.public_id, t.code, t.title, t.status,
    t.total_questions, t.open_questions_count, t.visibility, t.subject,
    t.created_at, t.finished_at, t.template_id,
    COALESCE(NULLIF(p.full_name, ''), NULLIF(t.publisher_name, ''), 'Ism hali kiritilmagan') AS publisher_name,
    COALESCE(tt.price_uzs, 5000) AS standard_price_uzs,
    s.id AS submission_id, d.revision AS draft_revision,
    CASE WHEN t.status = 'finished' THEN s.total_score END AS score,
    CASE WHEN t.status = 'finished' THEN s.rank END AS rank
    FROM tests t LEFT JOIN profiles p ON p.user_id = t.created_by
    LEFT JOIN test_templates tt ON tt.id = t.template_id
    LEFT JOIN submissions s ON s.test_id = t.id AND s.user_id = ?
    LEFT JOIN answer_drafts d ON d.test_id = t.id AND d.user_id = ? """


def publication_metadata(visibility, subject):
    if visibility not in ("public", "unlisted"):
        raise PlatformError("Ochiq yoki havola orqali ko‘rinishni tanlang.")
    if not isinstance(subject, str) or len(subject) > 80 or any(ord(c) < 32 for c in subject):
        raise PlatformError("Fan nomi 80 belgidan oshmasin.")
    return visibility, subject.strip()


async def profile(user_id):
    async with get_db_connection() as db:
        return await one(db, "SELECT full_name FROM profiles WHERE user_id = ?", (user_id,))


async def save_profile(user_id, name):
    if not isinstance(name, str) or len(name) > 150 or any(ord(c) < 32 for c in name):
        raise PlatformError("Ism va familiyangizni kiriting (150 belgigacha).")
    name = " ".join(name.split())
    if len(name.split()) < 2 or any(not any(c.isalpha() for c in word) for word in name.split()) or any(c.isdigit() or c in "@<>/" for c in name):
        raise PlatformError("To‘liq ism va familiyangizni kiriting. Telegram username yetarli emas.")
    async with get_db_connection() as db:
        await db.execute("INSERT INTO profiles(user_id, full_name) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET full_name = excluded.full_name, updated_at = CURRENT_TIMESTAMP", (user_id, name))
        await db.commit()
    return {"full_name": name}


async def publisher_name(db, user_id):
    record = await one(db, "SELECT full_name FROM profiles WHERE user_id = ?", (user_id,))
    if not record:
        raise PlatformError("Nashr qilishdan oldin profilingizda to‘liq ism va familiyangizni saqlang.", 409)
    return record["full_name"]


def share_url(test, bot_username=None):
    if bot_username:
        # Bot /start works without requiring a BotFather Main Mini App setting.
        return f"https://t.me/{bot_username}?start=t_{test['public_id']}"
    url = urlsplit(config.MINI_APP_URL)
    query = dict(parse_qsl(url.query))
    query["test"] = test["public_id"]
    return urlunsplit(url._replace(query=urlencode(query)))


async def summary(test_id, user_id):
    async with get_db_connection() as db:
        result = await one(db, SUMMARY_SQL + " WHERE t.id = ?", (user_id, user_id, test_id))
    if not result:
        raise PlatformError("Test topilmadi.", 404)
    return result


async def list_tests(user_id, *, scope="public", query="", subject="", before=None):
    query, subject = query.strip()[:150], subject.strip()[:80]
    conditions = ["t.document_json IS NOT NULL", "t.status IN ('active', 'finished')"]
    args = [user_id, user_id]
    if scope == "public":
        conditions += ["t.visibility = 'public'", "t.status = 'active'", "COALESCE(p.full_name, t.publisher_name) != ''"]
    elif scope == "drafts":
        conditions += ["d.user_id IS NOT NULL", "s.id IS NULL"]
    elif scope == "results":
        conditions += ["s.id IS NOT NULL"]
    elif scope == "teacher":
        conditions += ["t.created_by = ?"]
        args.append(user_id)
        # Legacy answer-key-only tests remain manageable by their owner.
        conditions.remove("t.document_json IS NOT NULL")
    else:
        raise PlatformError("Noma’lum bo‘lim.")
    if query:
        conditions.append("(instr(lower(t.title), lower(?)) > 0 OR instr(lower(COALESCE(p.full_name, t.publisher_name)), lower(?)) > 0 OR instr(lower(t.subject), lower(?)) > 0)")
        args.extend([query] * 3)
    if subject:
        conditions.append("t.subject = ?")
        args.append(subject)
    if before is not None:
        if type(before) is not int or before < 1:
            raise PlatformError("Sahifa belgisi noto‘g‘ri.")
        conditions.append("t.id < ?")
        args.append(before)
    async with get_db_connection() as db:
        counts = await one(db, """SELECT COUNT(*) AS total, COALESCE(SUM(status = 'active'), 0) AS active,
            (SELECT COUNT(*) FROM imports WHERE owner_id = ? AND status = 'review') AS review
            FROM tests WHERE created_by = ?""", (user_id, user_id)) if scope == 'teacher' else None
        result = await rows(db, SUMMARY_SQL + " WHERE " + " AND ".join(conditions) + " ORDER BY t.id DESC LIMIT 25", args)
        subjects = await rows(db, "SELECT DISTINCT subject FROM tests WHERE visibility = 'public' AND status = 'active' AND document_json IS NOT NULL AND subject != '' ORDER BY subject LIMIT 100")
    return {"items": result[:24], "next_cursor": result[23]["id"] if len(result) > 24 else None,
            "subjects": [item["subject"] for item in subjects], **({"counts": counts} if counts is not None else {})}


async def create_session(db, owner_id, template, name, visibility, subject):
    code = "T-" + str(secrets.randbelow(900000) + 100000)
    while await one(db, "SELECT id FROM tests WHERE code = ?", (code,)):
        code = "T-" + str(secrets.randbelow(900000) + 100000)
    document = TestDocument.model_validate_json(template["document_json"])
    cursor = await db.execute("""INSERT INTO tests(code, title, created_by, total_questions, open_questions_count,
        document_json, source_import_id, template_id, public_id, visibility, subject, publisher_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (code, document.title, owner_id, len(document.questions), sum(q.kind == "open" for q in document.questions),
         template["document_json"], template["source_import_id"], template["id"], uuid.uuid4().hex, visibility, subject, name))
    test_id = cursor.lastrowid
    await db.executemany("INSERT INTO questions(test_id, question_num, question_type, correct_answer, ai_instructions, assigned_points, content_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(test_id, q.number, "open" if q.kind == "open" else "closed", q.answer or None, q.rubric,
          q.points if q.kind == "open" else None, q.model_dump_json()) for q in document.questions])
    return test_id


async def new_session(test_id, owner_id, request_key):
    # A client-generated UUID makes retries safe after a lost HTTP response.
    if not isinstance(request_key, str) or len(request_key) != 32 or any(c not in "0123456789abcdef" for c in request_key):
        raise PlatformError("Sessiya so‘rovi noto‘g‘ri.")
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        source = await one(db, "SELECT * FROM tests WHERE id = ?", (test_id,))
        require_owner(source, owner_id)
        template = await one(db, "SELECT * FROM test_templates WHERE id = ? AND owner_id = ?", (source["template_id"], owner_id))
        if not template:
            raise PlatformError("Bu testda qayta ishlatiladigan savollar yo‘q.", 409)
        name = await publisher_name(db, owner_id)
        prior = await one(db, "SELECT test_id FROM session_requests WHERE owner_id = ? AND request_key = ?", (owner_id, request_key))
        if prior:
            return prior["test_id"]
        created = await create_session(db, owner_id, template, name, source["visibility"], source["subject"])
        await db.execute("INSERT INTO session_requests VALUES (?, ?, ?)", (owner_id, request_key, created))
        await db.commit()
    return created


async def update_listing(test_id, owner_id, visibility, subject):
    visibility, subject = publication_metadata(visibility, subject)
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        test = await one(db, "SELECT * FROM tests WHERE id = ?", (test_id,))
        require_owner(test, owner_id)
        name = await publisher_name(db, owner_id)
        if not test["document_json"]:
            raise PlatformError("Avval savol matnlari yuklangan test yarating.", 409)
        await db.execute("UPDATE tests SET visibility = ?, subject = ?, publisher_name = ? WHERE id = ?", (visibility, subject, name, test_id))
        await db.commit()
