import asyncio
import io
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, Update, User
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

import config
from handlers import import_upload
from keyboards.inline import get_mini_app_keyboard
from scripts.database.db import get_db_connection, init_db
from services import import_service, upload_service
from services.job_worker import execute_job, notify
from services.platform_service import PlatformError, get_import, one, rows
from services.telegram_auth import make_session
from services.test_document import TestDocument as Document
from services.web_app import BOT_USERNAME_KEY, create_web_app


@pytest.fixture
async def upload_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_PATH', str(tmp_path / 'upload.sqlite3'))
    monkeypatch.setattr(config, 'MEDIA_PATH', str(tmp_path / 'media'))
    monkeypatch.setattr(config, 'ADMIN_IDS', [111, 222])
    monkeypatch.setattr(config, 'BOT_TOKEN', '123456:fake-token')
    monkeypatch.setattr(config, 'MINI_APP_URL', 'https://mini.example')
    monkeypatch.setattr(upload_service, 'upload_locks', defaultdict(asyncio.Lock))
    monkeypatch.setattr(import_upload, 'upload_locks', upload_service.upload_locks)
    await init_db()
    return tmp_path


def photo_bytes():
    output = io.BytesIO()
    Image.new('RGB', (50, 70), 'white').save(output, 'PNG')
    return output.getvalue()


def fake_message(message_id=1, *, photo=False, owner=111, size=None, chat_type='private', filename='test.pdf'):
    document = SimpleNamespace(file_id='telegram-file', file_name=filename, file_size=size, mime_type='application/pdf')
    return SimpleNamespace(
        from_user=SimpleNamespace(id=owner), chat=SimpleNamespace(id=owner, type=chat_type),
        message_id=message_id, document=None if photo else document,
        photo=[SimpleNamespace(file_id='photo-file', file_size=size)] if photo else None,
        answer=AsyncMock(),
    )


def downloading_bot(content):
    async def download(file_id, destination, timeout):
        destination.write(content)
        destination.seek(0)
    return SimpleNamespace(download=AsyncMock(side_effect=download))


@pytest.mark.asyncio
async def test_forwarded_pdf_is_queued_once_and_links_its_own_draft(upload_db):
    message = fake_message()
    bot = downloading_bot(b'%PDF-1.7\nexample')
    await import_upload.receive_upload(message, bot)
    await import_upload.receive_upload(message, bot)
    assert bot.download.await_count == 1
    async with get_db_connection() as db:
        imported = await one(db, 'SELECT * FROM imports')
        assert imported['owner_id'] == 111 and imported['status'] == 'queued'
        assert len(await rows(db, "SELECT * FROM jobs WHERE kind = 'import'")) == 1
        assert len(await rows(db, 'SELECT * FROM telegram_uploads')) == 1
    keyboard = message.answer.await_args.kwargs['reply_markup']
    assert '?import=' + imported['id'] in keyboard.inline_keyboard[0][0].web_app.url
    assert (await get_import(imported['id'], 111))['assets'][0]['original_name'] == 'test.pdf'


@pytest.mark.asyncio
async def test_photo_album_stays_one_import_and_uses_telegram_message_order(upload_db):
    bot = downloading_bot(photo_bytes())
    # Simulate downloads that finish in a different order from sent pages.
    await import_upload.receive_upload(fake_message(30, photo=True), bot)
    await import_upload.receive_upload(fake_message(10, photo=True), bot)
    await import_upload.receive_upload(fake_message(20, photo=True), bot)
    async with get_db_connection() as db:
        imported = await one(db, 'SELECT * FROM imports')
        assert imported['status'] == 'collecting'
        assert len(await rows(db, 'SELECT * FROM imports')) == 1
        assert not await one(db, "SELECT * FROM jobs WHERE kind = 'import'")
        sources = await rows(db, "SELECT source_order FROM assets ORDER BY COALESCE(source_order, rowid), rowid")
        assert [source['source_order'] for source in sources] == [10, 20, 30]
    await init_db()  # Collection is durable across a restart, not stored in FSM.
    assert (await upload_service.active_collection(111, 111))['import_id'] == imported['id']
    await asyncio.gather(upload_service.start_collection(imported['id'], 111), upload_service.start_collection(imported['id'], 111))
    async with get_db_connection() as db:
        assert len(await rows(db, "SELECT * FROM jobs WHERE kind = 'import'")) == 1
        assert not await one(db, 'SELECT * FROM telegram_collections')
    assert (await get_import(imported['id'], 111))['status'] == 'queued'


@pytest.mark.asyncio
async def test_start_waits_for_already_arrived_photo_download(upload_db):
    started, release = asyncio.Event(), asyncio.Event()
    async def download(file_id, destination, timeout):
        started.set()
        await release.wait()
        destination.write(photo_bytes())
    message = fake_message(photo=True)
    upload = asyncio.create_task(import_upload.receive_upload(message, SimpleNamespace(download=download)))
    await started.wait()
    done_message = fake_message(2)
    done = asyncio.create_task(import_upload.cmd_done(done_message))
    await asyncio.sleep(0)
    assert not done.done()
    release.set()
    await asyncio.gather(upload, done)
    async with get_db_connection() as db:
        assert (await one(db, 'SELECT status FROM imports'))['status'] == 'queued'
        assert len(await rows(db, "SELECT * FROM jobs WHERE kind = 'import'")) == 1


@pytest.mark.asyncio
async def test_import_start_and_receipts_enforce_ownership(upload_db):
    source = await upload_service.store_source(photo_bytes(), 'page.png')
    imported = await upload_service.receive_telegram_source(111, 111, 1, source)
    with pytest.raises(PlatformError):
        await upload_service.start_collection(imported['id'], 222)
    with pytest.raises(PlatformError):
        await upload_service.telegram_receipt(111, 1, 222)
    assert (await get_import(imported['id'], 111))['status'] == 'collecting'


@pytest.mark.asyncio
async def test_non_admin_group_upload_and_oversize_are_rejected_before_download(upload_db):
    bot = downloading_bot(b'%PDF-test')
    for message in [fake_message(owner=9001), fake_message(chat_type='group'), fake_message(size=config.MAX_UPLOAD_BYTES + 1)]:
        await import_upload.receive_upload(message, bot)
        message.answer.assert_awaited_once()
    assert bot.download.await_count == 0
    async with get_db_connection() as db:
        assert not await one(db, 'SELECT * FROM imports')


@pytest.mark.asyncio
async def test_content_validation_and_download_cap_do_not_trust_metadata(upload_db, monkeypatch):
    message = fake_message()
    await import_upload.receive_upload(message, downloading_bot(b'not really a PDF'))
    async with get_db_connection() as db:
        assert not await one(db, 'SELECT * FROM imports')
    assert list(upload_service.media_file('a' * 32 + '.jpg').parent.iterdir()) == []
    monkeypatch.setattr(config, 'MAX_UPLOAD_BYTES', 10)
    await import_upload.receive_upload(fake_message(2), downloading_bot(b'x' * 11))
    async with get_db_connection() as db:
        assert not await one(db, 'SELECT * FROM telegram_uploads')


@pytest.mark.asyncio
async def test_photo_collection_total_limit_rolls_back_and_removes_unregistered_file(upload_db, monkeypatch):
    data = photo_bytes()
    monkeypatch.setattr(config, 'MAX_UPLOAD_BYTES', len(data) + 5)
    bot = downloading_bot(data)
    await import_upload.receive_upload(fake_message(1, photo=True), bot)
    await import_upload.receive_upload(fake_message(2, photo=True), bot)
    async with get_db_connection() as db:
        assert len(await rows(db, 'SELECT * FROM assets')) == 1
        assert len(await rows(db, 'SELECT * FROM telegram_uploads')) == 1
    assert len(list(upload_service.media_file('a' * 32 + '.jpg').parent.iterdir())) == 1


@pytest.mark.asyncio
async def test_unknown_download_failure_does_not_leak_credentials(upload_db):
    message = fake_message()
    bot = SimpleNamespace(download=AsyncMock(side_effect=RuntimeError('secret-token-do-not-show')))
    await import_upload.receive_upload(message, bot)
    assert 'secret-token-do-not-show' not in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_native_import_ready_notification_is_durable_and_deep_linked(upload_db, monkeypatch):
    source = await upload_service.store_source(b'%PDF-source', 'test.pdf')
    uploaded = await upload_service.receive_telegram_source(111, 111, 1, source)
    monkeypatch.setattr(import_service, 'prepare_pages', AsyncMock(return_value=[{'page': 1}]))
    document = Document(title='Ona tili', questions=[{'number': i, 'kind': 'open', 'text': 'Savol', 'source_pages': [1]} for i in range(1, 6)])
    monkeypatch.setattr(import_service, 'extract_chunk', AsyncMock(return_value=(document, {})))
    await import_service.process_import(uploaded['id'])
    async with get_db_connection() as db:
        notification = await one(db, "SELECT * FROM jobs WHERE kind = 'notify'")
        assert notification['target'] == 'import:' + uploaded['id']
    bot = SimpleNamespace(send_message=AsyncMock())
    await notify(notification['target'], bot)
    assert bot.send_message.await_args.args[0] == 111
    assert '?import=' + uploaded['id'] in bot.send_message.await_args.kwargs['reply_markup'].inline_keyboard[0][0].web_app.url


@pytest.mark.asyncio
async def test_browser_upload_still_uses_shared_validation_and_bot_link(upload_db):
    app = create_web_app()
    app[BOT_USERNAME_KEY] = 'ExampleAssessmentBot'
    async with TestClient(TestServer(app)) as client:
        client.session.cookie_jar.update_cookies({'ayam_session': make_session({'id': 111})})
        profile = await (await client.get('/api/me')).json()
        assert profile['bot_import_url'] == 'https://t.me/ExampleAssessmentBot?start=import'
        form = FormData()
        form.add_field('files', b'%PDF-example', filename='test.pdf', content_type='application/pdf')
        response = await client.post('/api/admin/imports', data=form)
        assert response.status == 201
        import_id = (await response.json())['id']
        assert (await get_import(import_id, 111))['status'] == 'queued'


@pytest.mark.asyncio
async def test_dispatcher_routes_forwarded_pdf_before_legacy_excel_handler(upload_db, monkeypatch):
    from handlers import admin, common
    from states import AdminStates
    bot = Bot(config.BOT_TOKEN)
    replies = AsyncMock(return_value=None)
    bot.session = replies
    monkeypatch.setattr(bot, 'download', downloading_bot(b'%PDF-example').download)
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(common.router)
    dispatcher.include_router(import_upload.router)
    dispatcher.include_router(admin.router)
    state = dispatcher.fsm.get_context(bot=bot, chat_id=111, user_id=111)
    await state.set_state(AdminStates.waiting_for_test_input)
    update = Update.model_validate({'update_id': 1, 'message': {
        'message_id': 9, 'date': 1795250000, 'chat': {'id': 111, 'type': 'private'},
        'from': {'id': 111, 'is_bot': False, 'first_name': 'Teacher'},
        'document': {'file_id': 'file-id', 'file_unique_id': 'unique-id', 'file_name': 'forwarded.pdf', 'mime_type': 'application/pdf'},
        'forward_origin': {'type': 'hidden_user', 'date': 1795250000, 'sender_user_name': 'Another teacher'},
    }})
    await dispatcher.feed_update(bot, update)
    async with get_db_connection() as db:
        assert (await one(db, 'SELECT status FROM imports'))['status'] == 'queued'
    assert await state.get_state() is None
    assert 'PDF qabul qilindi' in replies.await_args.args[1].text
    await dispatcher.storage.close()


def test_review_keyboard_keeps_existing_query_parameters(upload_db):
    original = config.MINI_APP_URL
    config.MINI_APP_URL = 'https://mini.example/?source=telegram'
    try:
        keyboard = get_mini_app_keyboard(import_id='a' * 32)
        url = keyboard.inline_keyboard[0][0].web_app.url
        assert 'source=telegram' in url and 'import=' + 'a' * 32 in url
    finally:
        config.MINI_APP_URL = original
