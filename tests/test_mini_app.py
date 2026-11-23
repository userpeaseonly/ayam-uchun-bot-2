import asyncio
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

import config
from scripts.database.db import get_db_connection, init_db
from scripts.database.models import get_test_by_id
from services import platform_service as platform
from services.deepseek_client import AIUnavailable
from services.import_service import materialize_media, media_file
from services.job_worker import claim_job, execute_job, grade_answer, recover_jobs
from services.scoring_service import run_test_analytics_and_scoring
from services.telegram_auth import make_session, read_session, verify_init_data
from services.test_document import TestDocument as Document, student_document
from services.web_app import create_web_app


def signed_init(user_id=111, auth_date=None):
    values = {"auth_date": str(int(time.time()) if auth_date is None else auth_date),
              "query_id": "example", "user": json.dumps({"id": user_id, "first_name": "Ali"})}
    secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, "\n".join(f"{k}={values[k]}" for k in sorted(values)).encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


@pytest.fixture
async def platform_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setattr(config, "MEDIA_PATH", str(tmp_path / "media"))
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:fake-test-token")
    monkeypatch.setattr(config, "ADMIN_IDS", [111, 222])
    monkeypatch.setattr(config, "MINI_APP_URL", "")
    await init_db()
    from services.catalog_service import save_profile
    await save_profile(111, 'Dilnoza Karimova')
    return tmp_path


def document_data():
    questions = []
    for number in range(1, 5):
        questions.append({"number": number, "kind": "matching" if number == 4 else "choice", "text": f"{number}-savol **xato** so'zni toping",
                          "options": [{"label": label, "text": label + " matn"} for label in "ABCDEF"],
                          "answer": "F" if number == 4 else "A", "reviewed": True,
                          "passage_id": "p1_1" if number == 2 else None})
    questions.append({"number": 5, "kind": "open", "text": "Ikki qismli savol", "parts": [{"id": "a", "prompt": "Birinchi"}, {"id": "b", "prompt": "Ikkinchi"}],
                      "rubric": "a) suv, b) havo. Ikkalasi ham to'g'ri bo'lishi shart.", "reviewed": True})
    return Document.model_validate({"title": "Ona tili", "passages": [{"id": "p1_1", "title": "PAXTA", "text": "Qasddan xato yozilgan matn."}], "questions": questions}).model_dump()


async def reviewed_import(document=None, owner=111):
    import_id = await platform.create_import(owner, "Ona tili", [])
    async with get_db_connection() as db:
        await db.execute("UPDATE imports SET status = 'review', document_json = ? WHERE id = ?", (json.dumps(document or document_data()), import_id))
        await db.execute("UPDATE jobs SET status = 'done' WHERE target = ?", (import_id,))
        await db.commit()
    return import_id


async def published_test(document=None):
    import_id = await reviewed_import(document)
    test_id = await platform.publish_import(import_id, 111, 0)
    return await get_test_by_id(test_id)


def answers():
    return {"1": "A", "2": "A", "3": "B", "4": "F", "5": {"a": "suv", "b": "havo"}}


@pytest.mark.asyncio
async def test_telegram_auth_signature_age_tampering_and_duplicate_fields(platform_db):
    assert verify_init_data(signed_init())["id"] == 111
    for raw in [signed_init().replace("Ali", "Evil"), signed_init(auth_date=int(time.time()) - 4000),
                signed_init(auth_date=int(time.time()) + 120), signed_init() + "&auth_date=123", ""]:
        with pytest.raises(platform.PlatformError):
            verify_init_data(raw)
    token = make_session({"id": 111})
    assert read_session(token)["id"] == 111
    with pytest.raises(platform.PlatformError):
        read_session(token + "changed")


@pytest.mark.asyncio
async def test_migration_is_repeatable_and_preserves_existing_data(platform_db):
    test = await published_test()
    await init_db()
    assert (await get_test_by_id(test["id"]))["code"] == test["code"]
    async with get_db_connection() as db:
        assert (await platform.one(db, "SELECT COUNT(*) AS n FROM schema_migrations"))["n"] == 3


@pytest.mark.asyncio
async def test_migration_upgrades_legacy_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "old.sqlite3"))
    async with get_db_connection() as db:
        await db.executescript("""
            CREATE TABLE tests(id INTEGER PRIMARY KEY, code TEXT, title TEXT, created_by INTEGER,
                total_questions INTEGER, open_questions_count INTEGER, status TEXT, created_at TEXT, finished_at TEXT);
            CREATE TABLE questions(id INTEGER PRIMARY KEY, test_id INTEGER, question_num INTEGER,
                question_type TEXT, correct_answer TEXT, ai_instructions TEXT, assigned_tier TEXT,
                assigned_points REAL, correct_count INTEGER);
            CREATE TABLE submissions(id INTEGER PRIMARY KEY, test_id INTEGER, user_id INTEGER,
                first_name TEXT, last_name TEXT, username TEXT, total_correct INTEGER, total_score REAL,
                rank INTEGER, submitted_at TEXT);
            CREATE TABLE answers(id INTEGER PRIMARY KEY, submission_id INTEGER, question_id INTEGER,
                user_answer TEXT, is_correct INTEGER, points_awarded REAL, ai_feedback TEXT);
            INSERT INTO tests VALUES(1, 'T-1234', 'Existing test', 111, 5, 0, 'active', '', NULL);
        """)
        await db.commit()
    await init_db()
    assert (await get_test_by_id(1))["title"] == "Existing test"
    async with get_db_connection() as db:
        assert (await platform.rows(db, "PRAGMA table_info(answers)"))[-1]["name"] == "grading_status"


@pytest.mark.asyncio
async def test_publication_requires_review_keys_and_valid_structure(platform_db):
    document = document_data()
    document["questions"][0]["reviewed"] = False
    document["questions"][1]["answer"] = ""
    document["questions"][2]["passage_id"] = "missing"
    document["questions"][4]["rubric"] = ""
    import_id = await reviewed_import(document)
    with pytest.raises(platform.PlatformError):
        await platform.publish_import(import_id, 111, 0)
    with pytest.raises(platform.PlatformError) as denied:
        await platform.get_import(import_id, 222)
    assert denied.value.status == 404
    revision = await platform.save_import(import_id, 111, document_data(), 0)
    assert revision == 1
    with pytest.raises(platform.PlatformError):
        await platform.save_import(import_id, 111, document_data(), 0)
    test_id = await platform.publish_import(import_id, 111, 1)
    assert await platform.publish_import(import_id, 111, 1) == test_id
    with pytest.raises(platform.PlatformError):
        await platform.save_import(import_id, 111, document_data(), 1)


def test_sample_structure_preserves_44_numbered_questions_and_nine_open_parents():
    document = document_data()
    template = document["questions"][0]
    document["questions"] = [{**template, "number": number} for number in range(1, 36)]
    for number in range(36, 45):
        document["questions"].append({"number": number, "kind": "open", "text": "Savol", "rubric": "Tasdiqlangan mezon", "reviewed": True,
                                     "parts": [{"id": "a", "prompt": "a"}, {"id": "b", "prompt": "b"}] if number >= 40 else []})
    parsed = Document.model_validate(document)
    assert parsed.publication_errors() == []
    assert sum(q.kind == "open" for q in parsed.questions) == 9
    assert sum(len(q.parts) or 1 for q in parsed.questions if q.kind == "open") == 14


def test_student_payload_allowlist_hides_all_grading_and_source_information():
    payload = student_document(document_data())
    serialized = json.dumps(payload)
    for hidden in ['"answer"', '"rubric"', '"points"', '"reviewed"', '"source_pages"', '"warnings"', '"accepted_answers"']:
        assert hidden not in serialized
    assert len(payload["questions"][3]["options"]) == 6


@pytest.mark.asyncio
async def test_atomic_duplicate_submissions_and_no_early_scores(platform_db):
    test = await published_test()
    user = {"id": 9001, "first_name": "Ali"}
    first, second = await asyncio.gather(platform.submit_answers(test["id"], user, answers()), platform.submit_answers(test["id"], user, answers()))
    assert first == second
    async with get_db_connection() as db:
        assert (await platform.one(db, "SELECT COUNT(*) AS n FROM submissions"))["n"] == 1
        assert (await platform.one(db, "SELECT COUNT(*) AS n FROM answers"))["n"] == 5
        assert (await platform.one(db, "SELECT COUNT(*) AS n FROM jobs WHERE kind = 'grade'"))["n"] == 1
    result = await platform.submission_result(test["id"], user["id"])
    assert "score" not in result and "rank" not in result
    assert result["answers"][3]["correct"] is True
    assert result["answers"][4]["correct"] is None
    with pytest.raises(platform.PlatformError) as pending:
        await run_test_analytics_and_scoring(test["id"], finish=True, owner_id=111)
    assert pending.value.status == 409
    assert (await get_test_by_id(test["id"]))["status"] == "active"


@pytest.mark.asyncio
async def test_invalid_answers_rollback_entire_submission(platform_db):
    test = await published_test()
    for invalid in [{"1": "Z"}, {"99": "A"}, {"5": {"z": "unexpected"}}, {"1": ["A"]}]:
        with pytest.raises(platform.PlatformError):
            await platform.submit_answers(test["id"], {"id": 9001}, invalid)
    async with get_db_connection() as db:
        assert not await platform.one(db, "SELECT id FROM submissions")


@pytest.mark.asyncio
async def test_drafts_revision_lock_and_submission_freeze(platform_db):
    test = await published_test()
    assert await platform.save_draft(test["id"], 9001, answers(), 0) == 1
    assert (await platform.test_for_student(test["code"], 9001))["draft"] == answers()
    with pytest.raises(platform.PlatformError):
        await platform.save_draft(test["id"], 9001, {"1": "B"}, 0)
    await platform.submit_answers(test["id"], {"id": 9001}, answers())
    with pytest.raises(platform.PlatformError):
        await platform.save_draft(test["id"], 9001, {"1": "B"}, 1)


@pytest.mark.asyncio
async def test_partial_multipart_is_incorrect_without_billing_ai(platform_db):
    test = await published_test()
    partial = answers()
    partial["5"] = {"a": "suv"}
    await platform.submit_answers(test["id"], {"id": 9001}, partial)
    result = await platform.submission_result(test["id"], 9001)
    assert result["answers"][-1]["correct"] is False
    async with get_db_connection() as db:
        assert not await platform.one(db, "SELECT * FROM jobs WHERE kind = 'grade'")


@pytest.mark.asyncio
async def test_ai_outage_stays_pending_and_restart_recovers_job(platform_db, monkeypatch):
    from services.job_worker import ai_evaluator
    monkeypatch.setattr(ai_evaluator, "evaluate_open_answer", AsyncMock(side_effect=AIUnavailable("Temporarily unavailable")))
    test = await published_test()
    await platform.submit_answers(test["id"], {"id": 9001}, answers())
    job = await claim_job()
    await execute_job(job)
    result = await platform.submission_result(test["id"], 9001)
    assert result["answers"][-1]["correct"] is None
    async with get_db_connection() as db:
        await db.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (job["id"],))
        await db.commit()
    await recover_jobs()
    async with get_db_connection() as db:
        assert (await platform.one(db, "SELECT status FROM jobs WHERE id = ?", (job["id"],)))["status"] == "queued"


@pytest.mark.asyncio
async def test_teacher_override_wins_race_and_finalization_is_idempotent(platform_db, monkeypatch):
    from services.job_worker import ai_evaluator
    test = await published_test()
    await platform.submit_answers(test["id"], {"id": 9001}, answers())
    async with get_db_connection() as db:
        answer_id = (await platform.one(db, "SELECT id FROM answers WHERE grading_status = 'pending'"))["id"]
    async def evaluate(*args):
        await platform.override_answer(test["id"], 111, answer_id, True, "Teacher approved")
        return False, "AI result arrived late"
    monkeypatch.setattr(ai_evaluator, "evaluate_open_answer", evaluate)
    await grade_answer(answer_id)
    assert (await platform.submission_result(test["id"], 9001))["answers"][-1]["correct"] is True
    await run_test_analytics_and_scoring(test["id"], finish=True, owner_id=111)
    await run_test_analytics_and_scoring(test["id"], finish=True, owner_id=111)
    result = await platform.submission_result(test["id"], 9001)
    assert result["score"] > 0 and result["rank"] == 1
    async with get_db_connection() as db:
        assert (await platform.one(db, "SELECT COUNT(*) AS n FROM jobs WHERE kind = 'notify' AND target LIKE 'final:%'"))["n"] == 1
    with pytest.raises(platform.PlatformError):
        await platform.submit_answers(test["id"], {"id": 9002}, answers())
    with pytest.raises(platform.PlatformError):
        await platform.override_answer(test["id"], 111, answer_id, False, "late")


@pytest.mark.asyncio
async def test_close_submission_race_has_consistent_cohort(platform_db):
    test = await published_test()
    closed_answers = {str(i): "A" for i in range(1, 5)}
    outcomes = await asyncio.gather(platform.submit_answers(test["id"], {"id": 9001}, closed_answers),
                                    run_test_analytics_and_scoring(test["id"], finish=True, owner_id=111), return_exceptions=True)
    if isinstance(outcomes[0], Exception):
        assert isinstance(outcomes[0], platform.PlatformError)
        assert (await platform.teacher_results(test["id"], 111))["submissions"] == []
    else:
        assert (await platform.submission_result(test["id"], 9001))["rank"] == 1


@pytest.mark.asyncio
async def test_crop_materialization_and_asset_authorization(platform_db):
    from PIL import Image
    document = document_data()
    document["questions"][0]["media"] = [{"page": 1, "x": .1, "y": .2, "width": .5, "height": .4}]
    import_id = await reviewed_import(document)
    page_id = "a" * 64
    Image.new("RGB", (1000, 1400), "white").save(media_file(page_id + ".jpg"))
    async with get_db_connection() as db:
        await db.execute("INSERT INTO assets(id, import_id, kind, filename, mime, page) VALUES (?, ?, 'page', ?, 'image/jpeg', 1)", (page_id, import_id, page_id + ".jpg"))
        await db.commit()
    test_id = await platform.publish_import(import_id, 111, 0)
    test = await get_test_by_id(test_id)
    crop_id = json.loads(test["document_json"])["questions"][0]["media"][0]["asset_id"]
    with Image.open(media_file(crop_id + ".jpg")) as crop:
        assert crop.size == (500, 560)
    async with TestClient(TestServer(create_web_app())) as client:
        client.session.cookie_jar.update_cookies({"ayam_session": make_session({"id": 9001})})
        assert (await client.get('/api/assets/' + page_id)).status == 404
        assert (await client.get('/api/assets/' + crop_id)).status == 200
        assert (await client.get('/api/admin/imports/' + import_id)).status == 404


@pytest.mark.asyncio
async def test_api_session_csrf_owner_and_student_end_to_end(platform_db):
    test = await published_test()
    async with TestClient(TestServer(create_web_app())) as client:
        assert (await client.get('/api/me')).status == 401
        response = await client.post('/api/session', json={"init_data": signed_init(9001)})
        assert response.status == 200
        assert (await response.json())["is_admin"] is False
        assert response.cookies["ayam_session"]["httponly"]
        assert (await client.get('/api/admin/tests')).status == 200
        assert (await client.get('/api/tests/' + test["code"])).status == 200
        assert (await client.post('/api/tests/' + test["code"] + '/submit', json={"answers": answers()}, headers={"Origin": "https://evil.example"})).status == 403
        assert (await client.post('/api/tests/' + test["code"] + '/submit', json={"answers": answers()})).status == 200
        response = await client.get('/api/tests/' + test["code"] + '/result')
        assert "score" not in await response.json()
        assert (await client.post('/api/session', json={"init_data": signed_init(222)})).status == 200
        assert (await client.get(f'/api/admin/tests/{test["id"]}/results')).status == 404


@pytest.mark.asyncio
async def test_exact_accepted_answer_can_be_graded_without_ai(platform_db):
    document = document_data()
    document["questions"][-1].update(parts=[], rubric="", accepted_answers=["O‘simlik", "", " "])
    test = await published_test(document)
    values = answers()
    values["5"] = "  O'SIMLIK "
    await platform.submit_answers(test["id"], {"id": 9001}, values)
    assert (await platform.submission_result(test["id"], 9001))["answers"][-1]["correct"] is True


@pytest.mark.asyncio
async def test_import_resume_uses_saved_chunks_and_clears_ai_answer_keys(platform_db, monkeypatch):
    from services import import_service
    import_id = await platform.create_import(111, "Test", [])
    pages = [{"page": i, "id": str(i), "filename": "unused.jpg", "text_content": ""} for i in range(1, 7)]
    monkeypatch.setattr(import_service, "prepare_pages", AsyncMock(return_value=pages))
    first = Document.model_validate(document_data())
    async with get_db_connection() as db:
        await db.execute("INSERT INTO import_chunks VALUES (?, 0, ?)", (import_id, first.model_dump_json()))
        await db.commit()
    extract = AsyncMock(return_value=(Document(title="Test"), {}))
    monkeypatch.setattr(import_service, "extract_chunk", extract)
    await import_service.process_import(import_id)
    assert extract.await_count == 1
    assert (await platform.get_import(import_id, 111))["status"] == "review"


@pytest.mark.asyncio
async def test_extractor_discards_model_generated_grading_rules(platform_db, monkeypatch):
    from services import import_service
    mock = AsyncMock(return_value=(document_data(), {}))
    monkeypatch.setattr(import_service, "complete_json", mock)
    parsed, _ = await import_service.extract_chunk([], 1, 5)
    assert all(not q.answer and not q.rubric and not q.accepted_answers and not q.reviewed for q in parsed.questions)


@pytest.mark.asyncio
async def test_import_context_questions_do_not_duplicate_batch_boundaries(platform_db, monkeypatch):
    from services import import_service
    import_id = await platform.create_import(111, "Test", [])
    pages = [{"page": i} for i in range(1, 11)]
    monkeypatch.setattr(import_service, "prepare_pages", AsyncMock(return_value=pages))
    first = Document.model_validate(document_data())
    for q in first.questions:
        q.source_pages = [1]
    contextual = first.questions[0].model_copy(update={"number": 6, "source_pages": [6], "text": "Context-only copy"})
    first.questions.append(contextual)
    second = Document(title="Test", questions=[contextual.model_copy(update={"text": "Owned by second batch"})])
    monkeypatch.setattr(import_service, "extract_chunk", AsyncMock(side_effect=[(first, {}), (second, {})]))
    await import_service.process_import(import_id)
    result = await platform.get_import(import_id, 111)
    assert len(result["document"]["questions"]) == 6
    assert result["document"]["questions"][-1]["text"] == "Owned by second batch"


@pytest.mark.asyncio
async def test_100_concurrent_submissions_lock_once_and_finalize(platform_db):
    test = await published_test()
    # All closed answers plus a deliberately blank open answer: no paid network calls.
    values = {"1": "A", "2": "B", "3": "A", "4": "F"}
    await asyncio.gather(*(platform.submit_answers(test["id"], {"id": 10000 + i}, values) for i in range(100)))
    await run_test_analytics_and_scoring(test["id"], finish=True, owner_id=111)
    result = await platform.teacher_results(test["id"], 111)
    assert len(result["submissions"]) == 100
    assert len(result["answers"]) == 500
    assert all(s["rank"] is not None for s in result["submissions"])
