"""Timer boundaries, durable expiry, independent students and immutable deadlines."""
import asyncio
import json
import time
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

import config
from scripts.database.db import get_db_connection, init_db
from services import platform_service as platform, catalog_service as catalog, timer_service as timers
from services.job_worker import claim_job, execute_job, recover_jobs
from services.scoring_service import run_test_analytics_and_scoring
from services.telegram_auth import make_session
from services.test_document import TestDocument as Document
from services.web_app import create_web_app


@pytest.fixture
async def timer_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_PATH', str(tmp_path / 'timers.sqlite3'))
    monkeypatch.setattr(config, 'MEDIA_PATH', str(tmp_path / 'media'))
    monkeypatch.setattr(config, 'BOT_TOKEN', '123456:fake-timer-token')
    monkeypatch.setattr(config, 'ADMIN_IDS', [])
    monkeypatch.setattr(config, 'MINI_APP_URL', 'https://mini.example')
    clock = SimpleNamespace(value=time.time())
    monkeypatch.setattr(timers, 'current_time', lambda: clock.value)
    await init_db()
    await catalog.save_profile(101, 'Dilnoza Karimova')
    return clock


def document():
    return Document.model_validate({'title': 'Vaqtli test', 'questions': [
        {'number': n, 'kind': 'choice', 'text': f'{n}-savol', 'options': [
            {'label': label, 'text': label + ' variant'} for label in 'AB'], 'answer': 'A', 'reviewed': True}
        for n in range(1, 6)]}).model_dump()


async def publish(minutes=1, content=None):
    content = content or document()
    ident = await platform.create_import(101, content['title'], [])
    async with get_db_connection() as db:
        await db.execute("UPDATE imports SET status = 'review', document_json = ? WHERE id = ?", (json.dumps(content), ident))
        await db.execute("UPDATE jobs SET status = 'done' WHERE target = ?", (ident,))
        await db.commit()
    revision = await platform.save_import(ident, 101, content, 0, 'public', 'Ona tili', minutes)
    test_id = await platform.publish_import(ident, 101, revision)
    return await platform.load_test((await catalog.summary(test_id, 10))['public_id'])


@pytest.mark.asyncio
async def test_duration_validation_publication_and_new_session(timer_db):
    for value in [0, -1, 1441, 1.5, True, '60', [], {}]:
        with pytest.raises(platform.PlatformError):
            timers.validate_duration(value)
    test = await publish(45)
    assert (await catalog.summary(test['id'], 10))['duration_minutes'] == 45
    import_id = test['source_import_id']
    assert (await platform.get_import(import_id, 101))['duration_minutes'] == 45
    clone_id = await catalog.new_session(test['id'], 101, 'a' * 32)
    await catalog.update_listing(clone_id, 101, 'public', '', 30)
    assert (await catalog.summary(clone_id, 10))['duration_minutes'] == 30
    assert (await catalog.summary(test['id'], 10))['duration_minutes'] == 45
    await catalog.update_listing(clone_id, 101, 'public', '', None)
    assert (await catalog.summary(clone_id, 10))['duration_minutes'] is None
    with pytest.raises(platform.PlatformError):
        await catalog.update_listing(test['id'], 999, 'public', '', 30)


@pytest.mark.asyncio
async def test_reading_intro_does_not_start_timer_and_start_ignores_client_deadline(timer_db):
    test = await publish()
    async with TestClient(TestServer(create_web_app())) as client:
        client.session.cookie_jar.update_cookies({'ayam_session': make_session({'id': 10, 'first_name': 'Ali'})})
        assert (await client.get(f"/api/tests/{test['public_id']}/intro")).status == 200
        async with get_db_connection() as db:
            assert not await platform.one(db, 'SELECT * FROM timed_attempts')
        assert (await client.get('/api/tests/' + test['public_id'])).status == 409
        assert (await client.post(f"/api/tests/{test['public_id']}/draft", json={'answers': {'1': 'A'}, 'revision': 0})).status == 409
        assert (await client.post(f"/api/tests/{test['public_id']}/submit", json={'answers': {'1': 'A'}})).status == 409
        response = await client.post(f"/api/tests/{test['public_id']}/start", json={'deadline_at': 999999999999, 'user_id': 20, 'duration_minutes': 1440})
        assert response.status == 200
        timer = (await response.json())['timer']
        assert timer['deadline_at'] == timer_db.value + 60
        assert timer['server_now'] == timer_db.value
        async with get_db_connection() as db:
            assert (await platform.one(db, 'SELECT user_id FROM timed_attempts'))['user_id'] == 10


@pytest.mark.asyncio
async def test_resume_restart_and_concurrent_start_do_not_reset_deadline(timer_db):
    test = await publish()
    await asyncio.gather(*(timers.start_attempt(test['id'], {'id': 10}) for _ in range(8)))
    initial = (await platform.test_for_student(test['public_id'], 10))['timer']
    await platform.save_draft(test['id'], 10, {'1': 'A'}, 0)
    timer_db.value += 20
    await init_db()
    await recover_jobs()
    await timers.start_attempt(test['id'], {'id': 10})
    resumed = await platform.test_for_student(test['public_id'], 10)
    assert resumed['timer']['deadline_at'] == initial['deadline_at']
    assert resumed['draft'] == {'1': 'A'}
    await timers.start_attempt(test['id'], {'id': 11})
    other = (await platform.test_for_student(test['public_id'], 11))['timer']
    assert other['deadline_at'] == initial['deadline_at'] + 20
    async with get_db_connection() as db:
        assert (await platform.one(db, "SELECT COUNT(*) AS n FROM jobs WHERE kind = 'expire'"))['n'] == 2


@pytest.mark.asyncio
async def test_durable_expiry_worker_submits_saved_answers_with_app_closed(timer_db):
    test = await publish()
    await timers.start_attempt(test['id'], {'id': 10, 'first_name': 'Ali', 'last_name': 'Valiyev'})
    await platform.save_draft(test['id'], 10, {'1': 'A', '2': 'B'}, 0)
    assert await claim_job() is None  # Grading workers never consume expiry jobs.
    assert await claim_job(timers=True) is None  # Future deadline is not ready.
    timer_db.value += 61
    async with get_db_connection() as db:
        # Advance the queue scheduler as well as the deterministic assessment clock.
        await db.execute("UPDATE jobs SET available_at = 0, status = 'running' WHERE kind = 'expire'")
        await db.commit()
    await recover_jobs()
    job = await claim_job(timers=True)
    await execute_job(job)
    result = await platform.submission_result(test['id'], 10)
    assert result['auto_submitted'] and len(result['answers']) == 5
    assert [a['correct'] for a in result['answers']] == [True, False, False, False, False]
    assert 'score' not in result
    await execute_job(job)  # Safe replay after interruption.
    async with get_db_connection() as db:
        assert (await platform.one(db, 'SELECT COUNT(*) AS n FROM submissions'))['n'] == 1
        assert not await platform.one(db, 'SELECT * FROM answer_drafts')
        assert (await platform.one(db, 'SELECT first_name FROM submissions'))['first_name'] == 'Ali'
        assert (await platform.one(db, "SELECT COUNT(*) AS n FROM jobs WHERE kind = 'notify'"))['n'] == 1
        assert (await platform.one(db, "SELECT status FROM jobs WHERE kind = 'expire'"))['status'] == 'done'


@pytest.mark.asyncio
@pytest.mark.parametrize('late_action', ['draft', 'submit', 'read', 'timer'])
async def test_every_student_request_enforces_expiry_before_accepting_late_answers(timer_db, late_action):
    test = await publish()
    await timers.start_attempt(test['id'], {'id': 10})
    await platform.save_draft(test['id'], 10, {'1': 'B'}, 0)
    timer_db.value += 60  # Exactly at the deadline: incoming A must never replace saved B.
    if late_action == 'draft':
        with pytest.raises(platform.PlatformError, match='Vaqt tugadi'):
            await platform.save_draft(test['id'], 10, {'1': 'A'}, 1)
    elif late_action == 'submit':
        await platform.submit_answers(test['id'], {'id': 10}, {'1': 'A'})
    elif late_action == 'read':
        await platform.test_for_student(test['public_id'], 10)
    else:
        await timers.attempt_status(test['id'], 10)
    result = await platform.submission_result(test['id'], 10)
    assert result['auto_submitted'] and result['answers'][0]['correct'] is False
    async with get_db_connection() as db:
        assert (await platform.one(db, 'SELECT user_answer FROM answers ORDER BY id LIMIT 1'))['user_answer'] == 'B'


@pytest.mark.asyncio
async def test_manual_submit_expiry_race_creates_only_one_submission(timer_db):
    test = await publish()
    await timers.start_attempt(test['id'], {'id': 10})
    await platform.save_draft(test['id'], 10, {'1': 'A'}, 0)
    timer_db.value += 60
    await asyncio.gather(timers.expire_attempt(test['id'], 10), platform.submit_answers(test['id'], {'id': 10}, {'1': 'B'}), timers.attempt_status(test['id'], 10))
    async with get_db_connection() as db:
        assert (await platform.one(db, 'SELECT COUNT(*) AS n FROM submissions'))['n'] == 1
        assert (await platform.one(db, 'SELECT COUNT(*) AS n FROM answers'))['n'] == 5
    assert (await platform.submission_result(test['id'], 10))['answers'][0]['correct']


@pytest.mark.asyncio
async def test_early_manual_submission_cancels_expiry(timer_db):
    test = await publish()
    await timers.start_attempt(test['id'], {'id': 10})
    timer_db.value += 59
    sub_id = await platform.submit_answers(test['id'], {'id': 10}, {'1': 'A'})
    timer_db.value += 2
    await timers.expire_attempt(test['id'], 10)
    await timers.start_attempt(test['id'], {'id': 10})
    result = await platform.submission_result(test['id'], 10)
    assert result['id'] == sub_id and result['auto_submitted'] is False
    async with get_db_connection() as db:
        assert (await platform.one(db, "SELECT status FROM jobs WHERE kind = 'expire'"))['status'] == 'done'


@pytest.mark.asyncio
async def test_teacher_cannot_change_clock_or_finish_while_students_are_working(timer_db):
    test = await publish()
    await timers.start_attempt(test['id'], {'id': 10})
    with pytest.raises(platform.PlatformError, match='o‘zgartirib'):
        await catalog.update_listing(test['id'], 101, 'public', '', 120)
    with pytest.raises(platform.PlatformError, match='ishlamoqda'):
        await run_test_analytics_and_scoring(test['id'], finish=True, owner_id=101)
    assert (await platform.teacher_results(test['id'], 101))['test']['active_attempts'] == 1
    await catalog.update_listing(test['id'], 101, 'unlisted', 'Adabiyot', 1)  # Other metadata stays editable.
    timer_db.value += 60
    await run_test_analytics_and_scoring(test['id'], finish=True, owner_id=101)
    result = await platform.submission_result(test['id'], 10)
    assert result['auto_submitted'] and result['total_correct'] == 0
    assert result['score'] is None and result['rank'] is None
    assert result['scoring']['status'] == 'unavailable'


@pytest.mark.asyncio
async def test_untimed_tests_stay_compatible_but_start_locks_duration(timer_db):
    test = await publish(None)
    assert (await platform.test_for_student(test['public_id'], 10))['timer'] is None
    await timers.start_attempt(test['id'], {'id': 10})
    with pytest.raises(platform.PlatformError):
        await catalog.update_listing(test['id'], 101, 'public', '', 20)
    timer_db.value += 86400
    assert (await timers.attempt_status(test['id'], 10))['submission'] is None
    assert await platform.submit_answers(test['id'], {'id': 10}, {'1': 'A'})


@pytest.mark.asyncio
async def test_timeout_uses_normal_open_grading_and_never_reveals_points_early(timer_db):
    content = document()
    content['questions'][-1].update(kind='open', options=[], answer='', rubric='Suv deb javob berishi kerak.')
    test = await publish(content=content)
    await timers.start_attempt(test['id'], {'id': 10})
    await platform.save_draft(test['id'], 10, {'5': 'suv'}, 0)
    timer_db.value += 60
    await timers.expire_attempt(test['id'], 10)
    result = await platform.submission_result(test['id'], 10)
    assert result['auto_submitted'] and result['answers'][-1]['correct'] is None
    assert 'score' not in result and 'rank' not in result
    with pytest.raises(platform.PlatformError, match='tekshirilmoqda'):
        await run_test_analytics_and_scoring(test['id'], finish=True, owner_id=101)
    async with get_db_connection() as db:
        assert (await platform.one(db, "SELECT COUNT(*) AS n FROM jobs WHERE kind = 'grade'"))['n'] == 1


@pytest.mark.asyncio
async def test_worker_requeues_if_clock_moves_back_after_claim(timer_db):
    test = await publish()
    await timers.start_attempt(test['id'], {'id': 10})
    async with get_db_connection() as db:
        await db.execute("UPDATE jobs SET available_at = 0 WHERE kind = 'expire'")
        await db.commit()
    job = await claim_job(timers=True)
    await execute_job(job)
    assert await platform.submission_result(test['id'], 10) is None
    async with get_db_connection() as db:
        queued = await platform.one(db, "SELECT status, available_at FROM jobs WHERE kind = 'expire'")
        assert queued == {'status': 'queued', 'available_at': timer_db.value + 60}


@pytest.mark.asyncio
async def test_started_test_is_resumable_before_any_answer_is_saved(timer_db):
    test = await publish()
    await timers.start_attempt(test['id'], {'id': 10})
    page = await catalog.list_tests(10, scope='drafts')
    assert len(page['items']) == 1 and page['items'][0]['id'] == test['id']
    assert page['items'][0]['draft_revision'] == 0
    assert (await catalog.summary(test['id'], 10))['draft_revision'] == 0
    assert not (await catalog.list_tests(11, scope='drafts'))['items']
    timer_db.value += 60
    await timers.expire_attempt(test['id'], 10)
    assert not (await catalog.list_tests(10, scope='drafts'))['items']
    assert (await catalog.list_tests(10, scope='results'))['items'][0]['submission_id']


@pytest.mark.asyncio
async def test_closed_app_restart_expires_timed_test_but_keeps_untimed_draft(timer_db):
    timed = await publish(1)
    untimed = await publish(None)
    for test in (timed, untimed):
        await timers.start_attempt(test['id'], {'id': 10})
        await platform.save_draft(test['id'], 10, {'1': 'A'}, 0)
    timer_db.value += 7 * 86400
    async with get_db_connection() as db:
        # Recover a timer abandoned by an older deployment's retry limit.
        await db.execute("UPDATE jobs SET status = 'failed', attempts = 3 WHERE kind = 'expire'")
        await db.commit()
    await recover_jobs()
    job = await claim_job(timers=True)
    assert job is not None
    await execute_job(job)  # No student request is needed to trigger submission.
    timed_result = await platform.submission_result(timed['id'], 10)
    assert timed_result['auto_submitted'] and timed_result['answers'][0]['correct']
    assert await platform.submission_result(untimed['id'], 10) is None
    resumed = await platform.test_for_student(untimed['public_id'], 10)
    assert resumed['timer'] is None and resumed['draft'] == {'1': 'A'}
    drafts = await catalog.list_tests(10, scope='drafts')
    assert [test['id'] for test in drafts['items']] == [untimed['id']]
    # A timed attempt can never restart after expiry, even through /start.
    await timers.start_attempt(timed['id'], {'id': 10})
    reopened = await platform.test_for_student(timed['public_id'], 10)
    assert reopened['submission']['id'] == timed_result['id']
    assert reopened['timer']['deadline_at'] < timer_db.value


@pytest.mark.asyncio
async def test_auto_submission_keeps_retrying_after_repeated_temporary_failures(timer_db, monkeypatch):
    test = await publish()
    await timers.start_attempt(test['id'], {'id': 10})
    await platform.save_draft(test['id'], 10, {'1': 'A'}, 0)
    timer_db.value += 60
    expire = timers.expire_attempt
    calls = 0

    async def temporarily_unavailable(test_id, user_id):
        nonlocal calls
        calls += 1
        if calls <= 4:
            raise OSError('Temporary storage failure')
        return await expire(test_id, user_id)

    monkeypatch.setattr(timers, 'expire_attempt', temporarily_unavailable)
    for attempt in range(1, 6):
        async with get_db_connection() as db:
            await db.execute("UPDATE jobs SET available_at = 0 WHERE kind = 'expire'")
            await db.commit()
        job = await claim_job(timers=True)
        assert job is not None and job['attempts'] == attempt
        await execute_job(job)
        async with get_db_connection() as db:
            state = await platform.one(db, "SELECT status, available_at FROM jobs WHERE kind = 'expire'")
        if attempt <= 4:
            assert state['status'] == 'queued'
            assert time.time() < state['available_at'] <= time.time() + 300
        else:
            assert state['status'] == 'done'
    result = await platform.submission_result(test['id'], 10)
    assert result['auto_submitted'] and result['answers'][0]['correct']
