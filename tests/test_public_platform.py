"""Open publishing, discovery and isolated sessions, without live AI or payment calls."""
import asyncio
import json
import uuid

import pytest
from aiohttp.test_utils import TestClient, TestServer

import config
from scripts.database.db import get_db_connection, init_db
from scripts.database import migrations
from services import access_policy, catalog_service as catalog, platform_service as platform
from services.scoring_service import run_test_analytics_and_scoring
from services.telegram_auth import make_session
from services.test_document import TestDocument as Document
from services.web_app import BOT_USERNAME_KEY, create_web_app


@pytest.fixture
async def public_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_PATH', str(tmp_path / 'public.sqlite3'))
    monkeypatch.setattr(config, 'MEDIA_PATH', str(tmp_path / 'media'))
    monkeypatch.setattr(config, 'BOT_TOKEN', '123456:test-token')
    monkeypatch.setattr(config, 'ADMIN_IDS', [111])
    monkeypatch.setattr(config, 'MINI_APP_URL', 'https://mini.example')
    await init_db()
    return tmp_path


def content():
    return Document.model_validate({'title': 'Ona tili', 'questions': [
        {'number': n, 'kind': 'choice', 'text': f'{n}-savol', 'options': [
            {'label': 'A', 'text': 'Birinchi'}, {'label': 'B', 'text': 'Ikkinchi'}],
         'answer': 'A', 'reviewed': True} for n in range(1, 6)]}).model_dump()


async def draft(owner=9001):
    ident = await platform.create_import(owner, 'Ona tili', [])
    async with get_db_connection() as db:
        await db.execute("UPDATE imports SET status = 'review', document_json = ? WHERE id = ?", (json.dumps(content()), ident))
        await db.execute("UPDATE jobs SET status = 'done' WHERE target = ?", (ident,))
        await db.commit()
    return ident


async def publish(owner=9001, *, visibility='public', name='Dilnoza Karimova', subject='Ona tili'):
    await catalog.save_profile(owner, name)
    ident = await draft(owner)
    revision = await platform.save_import(ident, owner, content(), 0, visibility, subject)
    test_id = await platform.publish_import(ident, owner, revision)
    async with get_db_connection() as db:
        return await platform.one(db, 'SELECT * FROM tests WHERE id = ?', (test_id,))


@pytest.mark.asyncio
async def test_any_user_can_publish_but_full_name_is_required(public_db):
    ident = await draft()
    with pytest.raises(platform.PlatformError, match='ism'):
        await platform.publish_import(ident, 9001, 0)
    for invalid in ['', 'Dilnoza', '@dilnoza_karimova', 'Center 123', 'Name\nSurname', ['Name', 'Surname']]:
        with pytest.raises(platform.PlatformError):
            await catalog.save_profile(9001, invalid)
    await catalog.save_profile(9001, '  Dilnoza   Karimova ')
    test_id = await platform.publish_import(ident, 9001, 0)
    assert (await catalog.summary(test_id, 4))['publisher_name'] == 'Dilnoza Karimova'
    assert await platform.publish_import(ident, 9001, 0) == test_id
    async with get_db_connection() as db:
        assert (await platform.one(db, 'SELECT COUNT(*) AS n FROM test_templates'))['n'] == 1
    await catalog.save_profile(9001, 'Dilnoza Yusupova')
    assert (await catalog.summary(test_id, 4))['publisher_name'] == 'Dilnoza Yusupova'
    with pytest.raises(platform.PlatformError):
        await catalog.update_listing(test_id, 111, 'public', '')


@pytest.mark.asyncio
async def test_public_discovery_unlisted_links_and_personal_history(public_db):
    public = await publish()
    hidden = await publish(9002, visibility='unlisted', name='Aziz Rahimov', subject='Maxfiy fan')
    items = (await catalog.list_tests(10))['items']
    assert [item['id'] for item in items] == [public['id']]
    assert (await catalog.list_tests(10))['subjects'] == ['Ona tili']
    assert not (await catalog.list_tests(10, query='Aziz'))['items']
    assert (await catalog.list_tests(10, query='karimova'))['items'][0]['publisher_name'] == 'Dilnoza Karimova'
    assert not (await catalog.list_tests(10, subject='Matematika'))['items']
    payload = await platform.test_for_student(hidden['public_id'], 10)
    assert payload['publisher_name'] == 'Aziz Rahimov'
    assert 'rubric' not in json.dumps(payload) and 'correct_answer' not in json.dumps(payload)
    await platform.save_draft(hidden['id'], 10, {'1': 'A'}, 0)
    assert (await catalog.list_tests(10, scope='drafts'))['items'][0]['id'] == hidden['id']
    assert not (await catalog.list_tests(11, scope='drafts'))['items']
    await platform.submit_answers(hidden['id'], {'id': 10, 'first_name': 'Ali'}, {'1': 'A'})
    assert not (await catalog.list_tests(10, scope='drafts'))['items']
    own = (await catalog.list_tests(10, scope='results'))['items'][0]
    assert own['score'] is None and own['rank'] is None
    await run_test_analytics_and_scoring(hidden['id'], finish=True, owner_id=9002)
    own = (await catalog.list_tests(10, scope='results'))['items'][0]
    assert own['score'] > 0 and own['rank'] == 1
    assert not (await catalog.list_tests(11, scope='results'))['items']


@pytest.mark.asyncio
async def test_new_sessions_reuse_content_without_mixing_cohorts(public_db):
    first = await publish()
    values = {str(n): 'A' for n in range(1, 6)}
    await platform.submit_answers(first['id'], {'id': 10}, values)
    await run_test_analytics_and_scoring(first['id'], finish=True, owner_id=9001)
    original = await platform.submission_result(first['id'], 10)
    request_key = uuid.uuid4().hex
    a, b = await asyncio.gather(catalog.new_session(first['id'], 9001, request_key), catalog.new_session(first['id'], 9001, request_key))
    assert a == b and a != first['id']
    async with get_db_connection() as db:
        second = await platform.one(db, 'SELECT * FROM tests WHERE id = ?', (a,))
        assert second['template_id'] == first['template_id']
        assert second['public_id'] != first['public_id']
        assert second['status'] == 'active' and second['finished_at'] is None
        questions = await platform.rows(db, 'SELECT * FROM questions WHERE test_id = ?', (a,))
        assert all(q['correct_count'] == 0 and q['assigned_tier'] is None and q['assigned_points'] is None for q in questions)
        assert not await platform.one(db, 'SELECT id FROM submissions WHERE test_id = ?', (a,))
    await platform.submit_answers(a, {'id': 10}, {'1': 'B'})
    await run_test_analytics_and_scoring(a, finish=True, owner_id=9001)
    assert (await platform.submission_result(a, 10))['score'] == 0
    assert await platform.submission_result(first['id'], 10) == original
    assert len((await catalog.list_tests(10, scope='results'))['items']) == 2


@pytest.mark.asyncio
async def test_teacher_routes_are_open_but_owner_checks_include_platform_admins(public_db):
    test = await publish()
    ident = await draft()
    app = create_web_app()
    app[BOT_USERNAME_KEY] = 'ExampleAssessmentBot'
    async with TestClient(TestServer(app)) as client:
        for user_id in [9001, 9002, 111]:
            client.session.cookie_jar.update_cookies({'ayam_session': make_session({'id': user_id, 'first_name': 'Ali'})})
            me = await (await client.get('/api/me')).json()
            assert me['can_teach'] is True and me['is_admin'] == (user_id == 111)
            assert (await client.get('/api/teacher/tests')).status == 200
            if user_id == 9001:
                response = await client.get(f"/api/teacher/tests/{test['id']}/results")
                assert response.status == 200
                assert (await response.json())['test']['share_url'] == f"https://t.me/ExampleAssessmentBot?start=t_{test['public_id']}"
                continue
            for prefix in ['teacher', 'admin']:
                assert (await client.get(f"/api/{prefix}/tests/{test['id']}/results")).status == 404
                assert (await client.get(f"/api/{prefix}/tests/{test['id']}/report")).status == 404
                assert (await client.get(f'/api/{prefix}/imports/{ident}')).status == 404
                for action, data in [('finish', {}), ('retry-grading', {}), ('listing', {'visibility': 'public'}), ('session', {'request_key': uuid.uuid4().hex}), ('answers/123', {'correct': True})]:
                    assert (await client.post(f"/api/{prefix}/tests/{test['id']}/{action}", json=data)).status == 404
                assert (await client.post(f'/api/{prefix}/imports/{ident}/publish', json={'revision': 0})).status == 404


@pytest.mark.asyncio
async def test_catalog_metadata_and_profile_cannot_change_identity_or_expose_keys(public_db):
    test = await publish()
    async with TestClient(TestServer(create_web_app())) as client:
        assert (await client.get('/api/catalog')).status == 401
        client.session.cookie_jar.update_cookies({'ayam_session': make_session({'id': 10})})
        response = await client.put('/api/profile', json={'full_name': 'Nodira Salimova', 'user_id': 9001, 'is_admin': True})
        assert response.status == 200
        assert (await catalog.profile(9001))['full_name'] == 'Dilnoza Karimova'
        for path in ['/api/catalog', f"/api/tests/{test['public_id']}/intro"]:
            response = await client.get(path)
            assert response.status == 200
            text = await response.text()
            for secret in ['document_json', 'correct_answer', 'rubric', 'source_import_id', 'user_id', 'ai_feedback']:
                assert secret not in text
        assert (await client.get('/api/catalog?scope=teacher')).status == 400
        assert (await client.get('/api/catalog?before=invalid')).status == 400
        assert (await client.put('/api/profile', json={'full_name': 'Malika Valiyeva'}, headers={'Origin': 'https://evil.example'})).status == 403


@pytest.mark.asyncio
async def test_price_and_brand_metadata_do_not_enable_charging_or_teacher_privileges(public_db, monkeypatch):
    for owner in [111, 9001]:
        test = await publish(owner)
        payload = await platform.test_for_student(test['public_id'], 10)
        assert payload['access'] == {'allowed': True, 'reason': 'free_launch', 'charging_enabled': False,
            'standard_price_uzs': 5000, 'currency': 'UZS', 'brand_publisher': owner == 111}
        async with get_db_connection() as db:
            assert (await platform.one(db, 'SELECT price_uzs FROM test_templates WHERE id = ?', (test['template_id'],)))['price_uzs'] == 5000
    monkeypatch.setattr(config, 'ADMIN_IDS', [])
    assert (await platform.test_for_student(test['public_id'], 10))['access']['allowed']


@pytest.mark.asyncio
async def test_access_boundary_blocks_read_draft_submit_and_crop_together(public_db, monkeypatch):
    from PIL import Image
    from services.import_service import media_file
    test = await publish()
    # The crop belongs to approved published content; owners retain source access.
    crop_id = 'a' * 32
    document = json.loads(test['document_json'])
    document['questions'][0]['media'] = [{'page': 1, 'x': 0, 'y': 0, 'width': 1, 'height': 1, 'asset_id': crop_id}]
    Image.new('RGB', (10, 10), 'white').save(media_file(crop_id + '.jpg'))
    async with get_db_connection() as db:
        await db.execute('UPDATE tests SET document_json = ? WHERE id = ?', (json.dumps(document), test['id']))
        await db.execute("INSERT INTO assets(id, import_id, kind, filename, mime) VALUES (?, ?, 'crop', ?, 'image/jpeg')", (crop_id, test['source_import_id'], crop_id + '.jpg'))
        await db.commit()
    async def deny(db, test, user_id):
        raise platform.PlatformError('Access required', 403)
    monkeypatch.setattr(access_policy, 'require_access', deny)
    async with TestClient(TestServer(create_web_app())) as client:
        client.session.cookie_jar.update_cookies({'ayam_session': make_session({'id': 10})})
        assert (await client.get(f"/api/tests/{test['public_id']}/intro")).status == 200
        assert (await client.get('/api/tests/' + test['public_id'])).status == 403
        for action, data in [('draft', {'answers': {'1': 'A'}, 'revision': 0}), ('submit', {'answers': {'1': 'A'}})]:
            assert (await client.post(f"/api/tests/{test['public_id']}/{action}", json=data)).status == 403
        assert (await client.get('/api/assets/' + crop_id)).status == 404
        client.session.cookie_jar.update_cookies({'ayam_session': make_session({'id': 9001})})
        assert (await client.get('/api/assets/' + crop_id)).status == 200
    async with get_db_connection() as db:
        assert not await platform.one(db, 'SELECT * FROM answer_drafts')
        assert not await platform.one(db, 'SELECT * FROM submissions')


@pytest.mark.asyncio
async def test_listing_changes_and_pagination_never_discover_unlisted_tests(public_db):
    test = await publish()
    async with get_db_connection() as db:
        await db.executemany("""INSERT INTO tests(code, title, created_by, total_questions, open_questions_count, document_json,
            template_id, public_id, visibility, subject, publisher_name) VALUES (?, ?, 9001, 5, 0, ?, ?, ?, ?, ?, ?)""",
            [(f'T-{500000 + i}', f'Test {i}', test['document_json'], test['template_id'], uuid.uuid4().hex,
              'public' if i < 30 else 'unlisted', 'Ona tili', 'Dilnoza Karimova') for i in range(40)])
        await db.commit()
    page1 = await catalog.list_tests(10)
    page2 = await catalog.list_tests(10, before=page1['next_cursor'])
    assert len(page1['items']) == 24 and len(page2['items']) == 7
    assert len({item['id'] for item in page1['items'] + page2['items']}) == 31
    assert all(item['visibility'] == 'public' for item in page1['items'] + page2['items'])
    assert page2['next_cursor'] is None
    with pytest.raises(platform.PlatformError):
        await catalog.update_listing(test['id'], 9001, 'restricted', 'Ona tili')
    await catalog.update_listing(test['id'], 9001, 'unlisted', 'Ona tili')
    assert test['id'] not in [item['id'] for item in (await catalog.list_tests(10, before=page1['next_cursor']))['items']]
    assert (await platform.test_for_student(test['public_id'], 10))['id'] == test['id']


@pytest.mark.asyncio
async def test_v2_migration_preserves_sessions_results_and_sources_without_publication(public_db, monkeypatch):
    monkeypatch.setattr(config, 'DB_PATH', str(public_db / 'v2.sqlite3'))
    all_migrations = migrations.MIGRATIONS
    monkeypatch.setattr(migrations, 'MIGRATIONS', all_migrations[:2])
    await init_db()
    async with get_db_connection() as db:
        await db.execute("INSERT INTO imports(id, owner_id, title, status) VALUES ('old-import', 9001, 'Old test', 'published')")
        await db.execute("INSERT INTO tests(id, code, title, created_by, total_questions, document_json, source_import_id) VALUES (42, 'T-123456', 'Old test', 9001, 5, ?, 'old-import')", (json.dumps(content()),))
        await db.execute("INSERT INTO questions(id, test_id, question_num, question_type, correct_answer) VALUES (100, 42, 1, 'closed', 'A')")
        await db.execute("INSERT INTO submissions(id, test_id, user_id) VALUES (200, 42, 10)")
        await db.execute("INSERT INTO answers(id, submission_id, question_id, user_answer, is_correct) VALUES (300, 200, 100, 'A', 1)")
        await db.execute("INSERT INTO assets(id, import_id, kind, filename, mime) VALUES ('source', 'old-import', 'source', 'source.pdf', 'application/pdf')")
        await db.execute("INSERT INTO jobs(kind, target) VALUES ('notify', 'final:200')")
        await db.commit()
    monkeypatch.setattr(migrations, 'MIGRATIONS', all_migrations)
    await init_db()
    await init_db()
    async with get_db_connection() as db:
        test = await platform.one(db, 'SELECT * FROM tests WHERE id = 42')
        assert test['visibility'] == 'unlisted' and len(test['public_id']) == 32 and test['template_id'] == 42
        assert (await platform.one(db, 'SELECT user_answer FROM answers WHERE id = 300'))['user_answer'] == 'A'
        assert await platform.one(db, "SELECT * FROM assets WHERE id = 'source'")
        assert await platform.one(db, "SELECT * FROM jobs WHERE target = 'final:200'")
    assert not (await catalog.list_tests(10))['items']
    assert (await platform.test_for_student('T-123456', 10))['submission']['answers'][0]['correct'] is True
    await catalog.save_profile(9001, 'Legacy Teacher')
    await catalog.update_listing(42, 9001, 'public', 'Ona tili')
    assert (await catalog.list_tests(10))['items'][0]['publisher_name'] == 'Legacy Teacher'


@pytest.mark.asyncio
async def test_shared_bot_link_opens_the_selected_session(public_db):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from handlers.common import cmd_start
    test = await publish()
    message = SimpleNamespace(text='/start t_' + test['public_id'], from_user=SimpleNamespace(id=10, first_name='Ali'), answer=AsyncMock())
    state = AsyncMock()
    await cmd_start(message, state)
    keyboard = message.answer.await_args.kwargs['reply_markup']
    assert '?test=' + test['public_id'] in keyboard.inline_keyboard[0][0].web_app.url
    assert test['title'] in message.answer.await_args.args[0]
    state.clear.assert_awaited_once()


@pytest.mark.asyncio
async def test_teacher_counts_remain_complete_when_list_is_filtered(public_db):
    await publish()
    await publish(9002, name='Other Teacher')
    await draft(9001)
    page = await catalog.list_tests(9001, scope='teacher', query='not-present')
    assert not page['items']
    assert page['counts'] == {'total': 1, 'active': 1, 'review': 1}


@pytest.mark.asyncio
async def test_new_legacy_test_keeps_a_working_bot_share_link(public_db):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from handlers.common import cmd_start
    from scripts.database.models import create_test, get_test_by_id
    from states import StudentStates
    test_id = await create_test('T-987654', 'Legacy answer-key test', 111, 5, 0)
    async with get_db_connection() as db:
        await db.executemany("INSERT INTO questions(test_id, question_num, question_type, correct_answer) VALUES (?, ?, 'closed', 'A')", [(test_id, n) for n in range(1, 6)])
        await db.commit()
    test = await get_test_by_id(test_id)
    assert len(test['public_id']) == 32
    assert catalog.share_url(test, 'ExampleAssessmentBot').endswith('t_' + test['public_id'])
    message = SimpleNamespace(text='/start t_' + test['public_id'], from_user=SimpleNamespace(id=10, first_name='Ali'), answer=AsyncMock())
    state = AsyncMock()
    await cmd_start(message, state)
    state.set_state.assert_awaited_once_with(StudentStates.waiting_for_answers)
    assert message.answer.await_count == 1
    assert 'bitta xabarda' in message.answer.await_args.args[0]
    assert not (await catalog.list_tests(10))['items']
