"""Teacher-owned voice explanations, released per session after submission."""

import asyncio
import json
import math
import uuid

from scripts.database.db import get_db_connection
from services.import_service import media_file
from services.platform_service import PlatformError, one, rows, require_owner

MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_AUDIO_SECONDS = 120
MAX_IMPORT_AUDIO_BYTES = 64 * 1024 * 1024
encoding_slots = asyncio.Semaphore(2)


async def require_editable(import_id, owner_id):
    async with get_db_connection() as db:
        record = await one(db, 'SELECT * FROM imports WHERE id=?', (import_id,))
    require_owner(record, owner_id)
    if record['status'] != 'review':
        raise PlatformError('Izoh faqat nashrdan oldin yoziladi.', 409)
    return record


async def validate_references(db, import_id, document):
    allowed = {a['id'] for a in await rows(db, "SELECT id FROM assets WHERE import_id=? AND kind='explanation'", (import_id,))}
    if any(q.explanation_audio and q.explanation_audio not in allowed for q in document.questions):
        raise PlatformError('Ovozli izoh shu qoralamaga tegishli emas.')


async def run_media_tool(*args):
    try:
        process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                      stderr=asyncio.subprocess.DEVNULL)
    except FileNotFoundError:
        raise PlatformError('Ovoz xizmati sozlanmagan. Serverga ffmpeg o‘rnating.', 503)
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=20)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.communicate()
        raise
    if process.returncode:
        raise PlatformError('Audio faylni o‘qib bo‘lmadi. Qayta yozib ko‘ring.')
    return stdout


async def probe(path):
    data = await run_media_tool('ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
        '-show_entries', 'stream=codec_type:format=format_name,duration', '-of', 'json', str(path))
    return json.loads(data)


async def store_recording(import_id, owner_id, data):
    await require_editable(import_id, owner_id)
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise PlatformError('Ovozli izoh bo‘sh yoki 8 MB dan katta.', 413)
    asset_id = uuid.uuid4().hex
    source = media_file(asset_id + '.upload')
    target = media_file(asset_id + '.mp3')
    source.parent.mkdir(parents=True, exist_ok=True)
    committed = False
    try:
        await asyncio.to_thread(source.write_bytes, data)
        async with encoding_slots:
            info = await probe(source)
            streams = info.get('streams', [])
            formats = set(info.get('format', {}).get('format_name', '').split(','))
            if (len(streams) != 1 or streams[0].get('codec_type') != 'audio'
                    or not formats.intersection({'webm', 'ogg', 'mov', 'mp4', 'm4a', 'wav', 'mp3', 'flac'})):
                raise PlatformError('Faqat ovozli yozuv qabul qilinadi.')
            # Normalize browser WebM/Opus and iOS MP4/AAC to one playable format.
            # Decode at most 121 seconds; longer recordings are rejected, not cut.
            await run_media_tool('ffmpeg', '-nostdin', '-v', 'error', '-protocol_whitelist', 'file,pipe',
                '-i', str(source), '-map', '0:a:0', '-vn', '-t', str(MAX_AUDIO_SECONDS + 1),
                '-ac', '1', '-ar', '24000', '-c:a', 'libmp3lame', '-b:a', '64k',
                '-threads', '1', '-map_metadata', '-1', str(target))
            duration = float((await probe(target)).get('format', {}).get('duration', 0))
            if not math.isfinite(duration) or not 0 < duration <= MAX_AUDIO_SECONDS + 0.25:
                raise PlatformError('Ovozli izoh 2 daqiqadan oshmasligi kerak.')
        size = target.stat().st_size
        async with get_db_connection() as db:
            await db.execute('BEGIN IMMEDIATE')
            record = await one(db, 'SELECT * FROM imports WHERE id=?', (import_id,))
            require_owner(record, owner_id)
            if record['status'] != 'review':
                raise PlatformError('Test allaqachon nashr qilingan.', 409)
            used = await one(db, "SELECT COALESCE(SUM(source_size),0) AS size FROM assets WHERE import_id=? AND kind='explanation'", (import_id,))
            if used['size'] + size > MAX_IMPORT_AUDIO_BYTES:
                raise PlatformError('Bu qoralamadagi ovozli izohlar hajmi chegaraga yetdi.', 413)
            await db.execute("INSERT INTO assets(id,import_id,kind,filename,mime,source_size) VALUES (?,?,'explanation',?,'audio/mpeg',?)",
                             (asset_id, import_id, target.name, size))
            await db.commit()
            committed = True
        return {'id': asset_id, 'duration_seconds': round(duration, 2)}
    except (TimeoutError, asyncio.TimeoutError):
        raise PlatformError('Ovozni tayyorlash vaqti tugadi. Qayta urinib ko‘ring.', 503)
    finally:
        source.unlink(missing_ok=True)
        if not committed:
            target.unlink(missing_ok=True)


async def submitted_recording(code, asset_id, user_id):
    """Neither knowing an asset ID nor finishing another session grants access."""
    from services.access_policy import require_access
    async with get_db_connection() as db:
        test = await one(db, 'SELECT * FROM tests WHERE public_id=? OR code=?', (code.lower(), code.upper()))
        await require_access(db, test, user_id)
        if not await one(db, 'SELECT id FROM submissions WHERE test_id=? AND user_id=?', (test['id'], user_id)):
            raise PlatformError('Izoh test topshirilgandan keyin ochiladi.', 403)
        document = json.loads(test['document_json'] or '{}')
        if not any(q.get('explanation_audio') == asset_id for q in document.get('questions', [])):
            raise PlatformError('Izoh topilmadi.', 404)
        asset = await one(db, "SELECT * FROM assets WHERE id=? AND import_id=? AND kind='explanation'",
                          (asset_id, test['source_import_id']))
        if not asset:
            raise PlatformError('Izoh topilmadi.', 404)
    return asset
