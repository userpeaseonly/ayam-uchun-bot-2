import asyncio
import json
import uuid
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

import config
from scripts.database.db import get_db_connection
from services import platform_service as platform, catalog_service as catalog, practice_service as practice
from services.deepseek_client import AIUnavailable
from services.job_worker import claim_job, execute_job, recover_jobs
from services.telegram_auth import make_session
from services.web_app import create_web_app
from test_mini_app import platform_db, published_test, reviewed_import, document_data


@pytest.mark.asyncio
async def test_brand_curation_groups_exam_positions_and_deduplicates_sessions(platform_db):
    first = await published_test()
    assert (await practice.grid(9001))['max_number'] == 0
    with pytest.raises(platform.PlatformError):
        await practice.set_source(first['id'], 9001, True)
    await practice.set_source(first['id'], 111, True)
    second_session = await catalog.new_session(first['id'], 111, uuid.uuid4().hex)
    await practice.set_source(second_session, 222, True)
    assert all(b['total'] == 1 for b in (await practice.grid(9001))['numbers'])
    doc = document_data()
    doc['questions'][0]['answer'] = 'B'
    second = await published_test(doc)
    await practice.set_source(second['id'], 111, True)
    grid = await practice.grid(9001)
    assert grid['max_number'] == 5 and all(b['total'] == 2 for b in grid['numbers'])
    first_question = await practice.open_number(1, 9001)
    next_question = await practice.open_number(1, 9001, first_question['next_id'])
    assert next_question['number'] == 1 and next_question['previous_id'] == first_question['id']
    assert next_question['position'] == 2 and next_question['total'] == 2
    assert (await practice.open_number(1, 9001))['id'] == next_question['id']
    foreign = await reviewed_import(owner=9001)
    await catalog.save_profile(9001, 'Other Teacher')
    foreign_test = await platform.publish_import(foreign, 9001, 0)
    with pytest.raises(platform.PlatformError):
        await practice.set_source(foreign_test, 111, True)
    await practice.set_source(second['id'], 111, False)
    with pytest.raises(platform.PlatformError):
        await practice.question(next_question['id'], 9001)
    assert (await practice.open_number(1, 9001))['id'] == first_question['id']


@pytest.mark.asyncio
async def test_private_drafts_repeat_feedback_and_exam_isolation(platform_db):
    test = await published_test()
    await catalog.update_listing(test['id'], 111, 'public', '', 1)
    await practice.set_source(test['id'], 111, True)
    q = await practice.open_number(2, 9001)
    assert q['passage']['title'] == 'PAXTA'
    assert 'solution' not in q and 'rubric' not in json.dumps(q)
    saved = await practice.save_answer(q['id'], 9001, 'B', 0)
    assert saved['revision'] == 1
    assert (await practice.question(q['id'], 9002))['answer'] == ''
    with pytest.raises(platform.PlatformError, match='boshqa oynada'):
        await practice.save_answer(q['id'], 9001, 'C', 0)
    key = uuid.uuid4().hex
    checks = await asyncio.gather(*(practice.check_answer(q['id'], 9001, 'B', 1, key) for _ in range(2)))
    checked = checks[0]
    assert checked['check']['id'] == checks[1]['check']['id']
    assert checked['check']['correct'] is False and checked['solution']['answer'] == 'A'
    assert 'solution' not in await practice.question(q['id'], 9002)
    await practice.save_answer(q['id'], 9001, '', checked['revision'])
    repeated = await practice.question(q['id'], 9001)
    assert repeated['check'] is None and 'solution' not in repeated  # Persists across reloads.
    correct = await practice.check_answer(q['id'], 9001, 'A', repeated['revision'], uuid.uuid4().hex)
    assert correct['check']['correct'] is True
    bucket = next(b for b in (await practice.grid(9001))['numbers'] if b['number'] == 2)
    assert bucket['checked'] == bucket['correct'] == 1
    async with get_db_connection() as db:
        for table in ('submissions', 'answers', 'answer_drafts', 'timed_attempts'):
            assert (await platform.one(db, f'SELECT COUNT(*) AS n FROM {table}'))['n'] == 0
        assert (await platform.one(db, 'SELECT status FROM tests WHERE id=?', (test['id'],)))['status'] == 'active'
        assert (await platform.one(db, 'SELECT COUNT(*) AS n FROM practice_checks'))['n'] == 2


@pytest.mark.asyncio
async def test_durable_open_check_retries_and_no_ai_duplicate(platform_db, monkeypatch):
    test = await published_test()
    await practice.set_source(test['id'], 111, True)
    q = await practice.open_number(5, 9001)
    with pytest.raises(platform.PlatformError):
        await practice.check_answer(q['id'], 9001, {'a': 'suv'}, 0, uuid.uuid4().hex)
    key = uuid.uuid4().hex
    result = await practice.check_answer(q['id'], 9001, {'a': 'suv', 'b': 'havo'}, 0, key)
    assert result['check']['status'] == 'pending' and result['check']['correct'] is None
    again = await practice.check_answer(q['id'], 9001, {'a': 'suv', 'b': 'havo'}, 0, key)
    assert again['check']['id'] == result['check']['id']
    with pytest.raises(platform.PlatformError, match='kuting'):
        await practice.save_answer(q['id'], 9001, {}, result['revision'])
    from services.ai_service import ai_evaluator
    model = AsyncMock(side_effect=AIUnavailable('Unavailable'))
    monkeypatch.setattr(ai_evaluator, 'evaluate_open_answer', model)
    job = await claim_job()
    assert job['kind'] == 'practice_grade'
    job['attempts'] = 3
    await execute_job(job)
    assert (await practice.question(q['id'], 9001))['check']['status'] == 'failed'
    await practice.retry_check(q['id'], 9001)
    model.side_effect = None
    model.return_value = (True, 'Ikkala qism ham to‘g‘ri.')
    claimed = await claim_job()
    await recover_jobs()  # An interrupted worker must not lose this check.
    claimed = await claim_job()
    await execute_job(claimed)
    finished = await practice.question(q['id'], 9001)
    assert finished['check']['status'] == 'done' and finished['check']['correct'] is True
    assert 'suv' in model.await_args.args[2] and 'havo' in model.await_args.args[2]
    assert 'Birinchi' in model.await_args.args[1] and 'Ikkalasi ham' in model.await_args.args[1]
    assert model.await_count == 2
    with pytest.raises(platform.PlatformError):
        await practice.retry_check(q['id'], 9002)


@pytest.mark.asyncio
async def test_reference_answer_can_grade_without_ai(platform_db, monkeypatch):
    doc = document_data()
    doc['questions'][4].update(parts=[], accepted_answers=['Ona tili'], rubric='')
    test = await published_test(doc)
    await practice.set_source(test['id'], 111, True)
    q = await practice.open_number(5, 9001)
    from services.ai_service import ai_evaluator
    model = AsyncMock(side_effect=AssertionError('Exact answers must not call AI'))
    monkeypatch.setattr(ai_evaluator, 'evaluate_open_answer', model)
    checked = await practice.check_answer(q['id'], 9001, '  ONA   TILI ', 0, uuid.uuid4().hex)
    assert checked['check']['status'] == 'done' and checked['check']['correct']
    model.assert_not_awaited()


@pytest.mark.asyncio
async def test_100_students_check_the_same_practice_question_independently(platform_db):
    test = await published_test()
    await practice.set_source(test['id'], 111, True)
    q = await practice.open_number(1, 9001)
    results = await asyncio.gather(*(practice.check_answer(q['id'], 10000 + i,
        'A' if i % 2 else 'B', 0, uuid.uuid4().hex) for i in range(100)))
    assert sum(result['check']['correct'] for result in results) == 50
    assert len({result['check']['id'] for result in results}) == 100
    assert 'solution' not in await practice.question(q['id'], 9999)
    async with get_db_connection() as db:
        assert (await platform.one(db, 'SELECT COUNT(*) AS n FROM practice_checks'))['n'] == 100
        assert (await platform.one(db, 'SELECT COUNT(*) AS n FROM submissions'))['n'] == 0


@pytest.mark.asyncio
async def test_http_auth_csrf_media_gates_and_unpublishing(platform_db):
    test = await published_test()
    asset_id, source_id, audio_id = 'a' * 32, 'b' * 32, 'c' * 32
    async with get_db_connection() as db:
        doc = json.loads(test['document_json'])
        doc['questions'][0]['media'] = [{'page': 1, 'asset_id': asset_id}]
        doc['questions'][0]['explanation_audio'] = audio_id
        await db.execute('UPDATE tests SET document_json=? WHERE id=?', (json.dumps(doc), test['id']))
        await db.executemany('INSERT INTO assets(id,import_id,kind,filename,mime) VALUES (?,?,?,?,?)', [
            (asset_id, test['source_import_id'], 'crop', asset_id + '.jpg', 'image/jpeg'),
            (source_id, test['source_import_id'], 'source', source_id + '.pdf', 'application/pdf'),
            (audio_id, test['source_import_id'], 'explanation', audio_id + '.mp3', 'audio/mpeg')])
        await db.commit()
    media = platform_db / 'media'
    media.mkdir(exist_ok=True)
    (media / (asset_id + '.jpg')).write_bytes(b'crop')
    (media / (source_id + '.pdf')).write_bytes(b'original')
    (media / (audio_id + '.mp3')).write_bytes(b'audio')
    await practice.set_source(test['id'], 111, True)
    q = await practice.open_number(1, 9001)
    async with TestClient(TestServer(create_web_app())) as client:
        assert (await client.get('/api/practice/grid')).status == 401
        client.session.cookie_jar.update_cookies({'ayam_session': make_session({'id': 9001})})
        assert (await client.get(f"/api/practice/items/{q['id']}/assets/{asset_id}")).status == 200
        assert (await client.get(f"/api/practice/items/{q['id']}/assets/{source_id}")).status == 404
        assert (await client.get(f"/api/practice/items/{q['id']}/assets/{audio_id}")).status == 403
        endpoint = f"/api/practice/items/{q['id']}/check"
        payload = {'answer': 'A', 'revision': 0, 'request_key': uuid.uuid4().hex, 'user_id': 9002}
        assert (await client.post(endpoint, json=payload, headers={'Origin': 'https://evil.example'})).status == 403
        response = await client.post(endpoint, json=payload)
        assert response.status == 200 and (await response.json())['check']['correct'] is True
        assert (await client.get(f"/api/practice/items/{q['id']}/assets/{audio_id}")).status == 200
        client.session.cookie_jar.update_cookies({'ayam_session': make_session({'id': 9002})})
        assert (await client.get(f"/api/practice/items/{q['id']}/assets/{audio_id}")).status == 403
        assert (await client.put(f"/api/teacher/tests/{test['id']}/practice", json={'enabled': False})).status == 403
    await practice.set_source(test['id'], 111, False)
    assert not (await practice.grid(9001))['numbers']
    with pytest.raises(platform.PlatformError):
        await practice.asset(q['id'], audio_id, 9001)
