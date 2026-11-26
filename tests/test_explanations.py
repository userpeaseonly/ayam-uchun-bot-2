"""Real audio formats, ownership and per-student post-submission release."""

import asyncio
import json
import subprocess
import uuid
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

import config
from scripts.database.db import get_db_connection, init_db
from scripts.database.models import get_test_by_id
from services import platform_service as platform, explanation_service as audio, catalog_service as catalog
from services import timer_service as timers
from services.telegram_auth import make_session
from services.test_document import TestDocument as Document, student_document
from services.web_app import create_web_app


@pytest.fixture
async def voice_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_PATH', str(tmp_path / 'voice.sqlite3'))
    monkeypatch.setattr(config, 'MEDIA_PATH', str(tmp_path / 'media'))
    monkeypatch.setattr(config, 'BOT_TOKEN', '123456:voice-fixture')
    monkeypatch.setattr(config, 'MINI_APP_URL', 'https://mini.example')
    monkeypatch.setattr(config, 'ADMIN_IDS', [])
    await init_db()
    await catalog.save_profile(111, 'Dilnoza Karimova')


def sample_audio(container='webm', duration=0.3):
    codecs = {'webm': ['-c:a', 'libopus'], 'ogg': ['-c:a', 'libopus'],
              'mp4': ['-c:a', 'aac', '-movflags', 'frag_keyframe+empty_moov'],
              'wav': ['-c:a', 'pcm_s16le']}
    return subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi',
        '-i', f'sine=frequency=440:sample_rate=8000:duration={duration}',
        *codecs[container], '-f', container, 'pipe:1'], check=True, capture_output=True).stdout


async def draft(owner=111):
    document = Document.model_validate({'title': 'Ovozli test', 'questions': [
        {'number': n, 'kind': 'choice', 'text': f'{n}-savol', 'reviewed': True,
         'answer': 'A', 'options': [{'label': 'A', 'text': 'Ha'}, {'label': 'B', 'text': 'Yo‘q'}]}
        for n in range(1, 6)]}).model_dump()
    import_id = await platform.create_import(owner, document['title'], [])
    async with get_db_connection() as db:
        await db.execute("UPDATE imports SET status='review', document_json=? WHERE id=?", (json.dumps(document), import_id))
        await db.commit()
    return import_id, document


async def with_recording():
    import_id, document = await draft()
    item = await audio.store_recording(import_id, 111, sample_audio())
    document['questions'][0]['explanation_audio'] = item['id']
    revision = await platform.save_import(import_id, 111, document, 0)
    test_id = await platform.publish_import(import_id, 111, revision)
    return import_id, item, await get_test_by_id(test_id)


@pytest.mark.asyncio
@pytest.mark.parametrize('container', ['webm', 'mp4', 'ogg'])
async def test_browser_recording_formats_are_normalized_and_metadata_is_not_trusted(voice_db, container):
    import_id, _ = await draft()
    item = await audio.store_recording(import_id, 111, sample_audio(container))
    assert 0 < item['duration_seconds'] < 1
    async with get_db_connection() as db:
        saved = await platform.one(db, 'SELECT * FROM assets WHERE id=?', (item['id'],))
    assert saved['kind'] == 'explanation' and saved['mime'] == 'audio/mpeg'
    assert audio.media_file(saved['filename']).is_file()
    assert len(list(audio.media_file(saved['filename']).parent.glob('*.upload'))) == 0


@pytest.mark.asyncio
async def test_recording_rejects_invalid_oversized_long_and_foreign_uploads(voice_db, monkeypatch):
    import_id, _ = await draft()
    for payload in (b'', b'<html>pretending to be audio</html>', sample_audio('wav', duration=121)):
        with pytest.raises(platform.PlatformError):
            await audio.store_recording(import_id, 111, payload)
    with monkeypatch.context() as patch:
        patch.setattr(audio, 'MAX_AUDIO_BYTES', 3)
        with pytest.raises(platform.PlatformError):
            await audio.store_recording(import_id, 111, b'1234')
    with pytest.raises(platform.PlatformError):
        await audio.store_recording(import_id, 222, sample_audio())
    assert not list(Path(config.MEDIA_PATH).glob('*'))


@pytest.mark.asyncio
async def test_audio_references_require_same_draft_and_publication_rechecks(voice_db):
    first, document = await draft()
    second, _ = await draft()
    item = await audio.store_recording(second, 111, sample_audio())
    document['questions'][0]['explanation_audio'] = item['id']
    with pytest.raises(platform.PlatformError):
        await platform.save_import(first, 111, document, 0)
    # Reject forged legacy/direct DB content on publish too.
    async with get_db_connection() as db:
        await db.execute('UPDATE imports SET document_json=? WHERE id=?', (json.dumps(document), first))
        await db.commit()
    with pytest.raises(platform.PlatformError):
        await platform.publish_import(first, 111, 0)
    document['questions'][0]['explanation_audio'] = ''
    assert Document.model_validate(document).publication_errors() == []
    assert 'explanation_audio' not in json.dumps(student_document(document))


@pytest.mark.asyncio
async def test_decoder_timeout_and_storage_quota_cleanup_partial_files(voice_db, monkeypatch):
    import_id, _ = await draft()
    payload = sample_audio()
    async def timeout(*args):
        raise asyncio.TimeoutError()
    with monkeypatch.context() as patch:
        patch.setattr(audio, 'run_media_tool', timeout)
        with pytest.raises(platform.PlatformError) as error:
            await audio.store_recording(import_id, 111, payload)
        assert error.value.status == 503
    with monkeypatch.context() as patch:
        patch.setattr(audio, 'MAX_IMPORT_AUDIO_BYTES', 1)
        with pytest.raises(platform.PlatformError) as error:
            await audio.store_recording(import_id, 111, payload)
        assert error.value.status == 413
    assert not list(Path(config.MEDIA_PATH).glob('*'))
    async with get_db_connection() as db:
        assert not await platform.one(db, "SELECT id FROM assets WHERE kind='explanation'")


@pytest.mark.asyncio
async def test_voice_release_requires_own_submission_and_current_session_even_after_restart(voice_db):
    import_id, item, test = await with_recording()
    async with TestClient(TestServer(create_web_app())) as client:
        url = f"/api/tests/{test['public_id']}/explanations/{item['id']}"
        assert (await client.get(url)).status == 401
        client.session.cookie_jar.update_cookies({'ayam_session': make_session({'id': 9001})})
        student = await platform.test_for_student(test['public_id'], 9001)
        assert 'explanation_audio' not in json.dumps(student['document'])
        assert student['submission'] is None
        assert (await client.get(url)).status == 403
        assert (await client.get('/api/assets/' + item['id'])).status == 404
        await platform.submit_answers(test['id'], {'id': 9001}, {'1': 'B'})
        await init_db()  # Durability does not depend on recorder/browser state.
        result = await platform.submission_result(test['id'], 9001)
        assert result['answers'][0]['explanation_audio_url'] == url
        assert 'score' not in result
        assert 'explanation_audio_url' not in result['answers'][1]
        played = await client.get(url, headers={'Range': 'bytes=0-99'})
        assert played.status == 206 and played.content_type == 'audio/mpeg'
        assert len(await played.read()) == 100
        assert played.headers['Cache-Control'] == 'no-store'
        assert 'media-src' in played.headers['Content-Security-Policy']
        client.session.cookie_jar.update_cookies({'ayam_session': make_session({'id': 9002})})
        assert (await client.get(url)).status == 403
        second_id = await catalog.new_session(test['id'], 111, uuid.uuid4().hex)
        second = await get_test_by_id(second_id)
        client.session.cookie_jar.update_cookies({'ayam_session': make_session({'id': 9001})})
        other_url = f"/api/tests/{second['public_id']}/explanations/{item['id']}"
        assert (await client.get(other_url)).status == 403
        client.session.cookie_jar.update_cookies({'ayam_session': make_session({'id': 111})})
        assert (await client.get('/api/assets/' + item['id'])).status == 200
        assert (await client.post(f'/api/teacher/imports/{import_id}/explanations', data=b'audio')).status == 409


@pytest.mark.asyncio
async def test_http_upload_auth_csrf_stream_limit_and_automatic_submission(voice_db, monkeypatch):
    import_id, _ = await draft()
    endpoint = f'/api/teacher/imports/{import_id}/explanations'
    payload = sample_audio('mp4')
    async with TestClient(TestServer(create_web_app())) as client:
        assert (await client.post(endpoint, data=payload)).status == 401
        client.session.cookie_jar.update_cookies({'ayam_session': make_session({'id': 222})})
        assert (await client.post(endpoint, data=payload)).status == 404
        client.session.cookie_jar.update_cookies({'ayam_session': make_session({'id': 111})})
        assert (await client.post(endpoint, data=payload, headers={'Origin': 'https://evil.example'})).status == 403
        # A spoofed content type cannot bypass real decoding.
        uploaded = await client.post(endpoint, data=payload, headers={'Content-Type': 'application/octet-stream'})
        assert uploaded.status == 201
        item = await uploaded.json()
        with monkeypatch.context() as patch:
            patch.setattr(audio, 'MAX_AUDIO_BYTES', 10)
            async def chunks():
                yield b'123456'
                yield b'789012'
            assert (await client.post(endpoint, data=chunks())).status == 413
        record = await platform.get_import(import_id, 111)
        document = record['document']
        document['questions'][0]['explanation_audio'] = item['id']
        revision = await platform.save_import(import_id, 111, document, 0, duration_minutes=1)
        test_id = await platform.publish_import(import_id, 111, revision)
        test = await get_test_by_id(test_id)
        await timers.start_attempt(test_id, {'id': 9001})
        monkeypatch.setattr(timers, 'current_time', lambda: 10 ** 12)
        await timers.expire_attempt(test_id, 9001)
        result = await platform.submission_result(test_id, 9001)
        assert result['auto_submitted'] and result['answers'][0]['explanation_audio_url']
        client.session.cookie_jar.update_cookies({'ayam_session': make_session({'id': 9001})})
        assert (await client.get(result['answers'][0]['explanation_audio_url'])).status == 200
