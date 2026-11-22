"""One validated file intake for browser uploads and Telegram attachments."""

import asyncio
import io
import uuid
from collections import defaultdict
from pathlib import Path

import config
from scripts.database.db import get_db_connection
from services.import_service import media_file, normalize_image
from services.platform_service import PlatformError, one, require_owner

upload_locks = defaultdict(asyncio.Lock)


class LimitedDownload(io.BytesIO):
    def write(self, data):
        if self.tell() + len(data) > config.MAX_UPLOAD_BYTES:
            raise PlatformError("Fayl 20 MB dan oshmasin.", 413)
        return super().write(data)


async def store_source(content, original_name):
    if not content or len(content) > config.MAX_UPLOAD_BYTES:
        raise PlatformError("Fayl bo'sh yoki 20 MB dan katta.", 413)
    asset_id = uuid.uuid4().hex
    pdf = content.startswith(b"%PDF-")
    filename = asset_id + (".pdf" if pdf else ".jpg")
    path = media_file(filename)
    try:
        if pdf:
            await asyncio.to_thread(path.write_bytes, content)
        else:
            await asyncio.to_thread(normalize_image, io.BytesIO(content), path)
        return {"id": asset_id, "filename": filename, "mime": "application/pdf" if pdf else "image/jpeg",
                "original_name": Path(original_name or ("Test.pdf" if pdf else "Sahifa.jpg")).name[:200],
                "source_size": len(content)}
    except BaseException:
        path.unlink(missing_ok=True)
        raise


async def enforce_import_limit(db, owner_id):
    pending = await one(db, "SELECT COUNT(*) AS n FROM imports WHERE owner_id = ? AND status IN ('queued', 'processing', 'collecting')", (owner_id,))
    if pending["n"] >= 3:
        raise PlatformError("Avval navbatdagi importlar tugashini kuting.", 429)


async def telegram_receipt(chat_id, message_id, owner_id):
    async with get_db_connection() as db:
        receipt = await one(db, "SELECT * FROM telegram_uploads WHERE chat_id = ? AND message_id = ?", (chat_id, message_id))
        if receipt and receipt["owner_id"] != owner_id:
            raise PlatformError("Ruxsat yo'q.", 403)
        return receipt


async def receive_telegram_source(owner_id, chat_id, message_id, source):
    """Commit the attachment, receipt and queue transition together.

    The caller removes an unregistered source file after retries/errors.
    Telegram message order, rather than download completion order, orders pages.
    """
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        receipt = await one(db, "SELECT * FROM telegram_uploads WHERE chat_id = ? AND message_id = ?", (chat_id, message_id))
        if receipt:
            if receipt["owner_id"] != owner_id:
                raise PlatformError("Ruxsat yo'q.", 403)
            return {"id": receipt["import_id"], "registered": False, "first": False, "pdf": source["mime"] == "application/pdf"}
        pdf = source["mime"] == "application/pdf"
        collection = await one(db, "SELECT c.import_id FROM telegram_collections c JOIN imports i ON i.id = c.import_id WHERE c.chat_id = ? AND c.owner_id = ? AND i.status = 'collecting'", (chat_id, owner_id))
        first = pdf or not collection
        if first:
            await enforce_import_limit(db, owner_id)
            import_id = uuid.uuid4().hex
            title = Path(source["original_name"]).stem if pdf else "Telegram rasmlaridan test"
            await db.execute("INSERT INTO imports(id, owner_id, title, status) VALUES (?, ?, ?, ?)",
                             (import_id, owner_id, title[:300] or "Yangi test", "queued" if pdf else "collecting"))
            if pdf:
                await db.execute("INSERT INTO jobs(kind, target) VALUES ('import', ?)", (import_id,))
            else:
                await db.execute("INSERT INTO telegram_collections VALUES (?, ?, ?)", (chat_id, owner_id, import_id))
        else:
            import_id = collection["import_id"]
            sizes = await one(db, "SELECT COUNT(*) AS n, COALESCE(SUM(source_size), 0) AS bytes FROM assets WHERE import_id = ? AND kind = 'source'", (import_id,))
            if sizes["n"] >= config.MAX_IMPORT_PAGES or sizes["bytes"] + source["source_size"] > config.MAX_UPLOAD_BYTES:
                raise PlatformError("Rasmlar jami 20 MB va 30 sahifadan oshmasin.", 413)
        await db.execute("INSERT INTO assets(id, import_id, kind, filename, mime, original_name, source_size, source_order) VALUES (?, ?, 'source', ?, ?, ?, ?, ?)",
                         (source["id"], import_id, source["filename"], source["mime"], source["original_name"], source["source_size"], message_id))
        await db.execute("INSERT INTO telegram_uploads VALUES (?, ?, ?, ?)", (chat_id, message_id, owner_id, import_id))
        await db.commit()
    return {"id": import_id, "registered": True, "first": first, "pdf": pdf}


async def start_collection(import_id, owner_id):
    # Wait behind already-arrived photo downloads before exposing the import job.
    async with upload_locks[owner_id]:
        return await _start_collection(import_id, owner_id)


async def _start_collection(import_id, owner_id):
    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        record = await one(db, "SELECT * FROM imports WHERE id = ?", (import_id,))
        require_owner(record, owner_id)
        if record["status"] in ("queued", "processing", "review", "published"):
            return import_id
        if record["status"] != "collecting":
            raise PlatformError("Bu importni boshlash mumkin emas.", 409)
        sources = await one(db, "SELECT COUNT(*) AS n FROM assets WHERE import_id = ? AND kind = 'source'", (import_id,))
        if not sources["n"]:
            raise PlatformError("Avval rasmlarni yuboring.")
        await db.execute("INSERT INTO jobs(kind, target) VALUES ('import', ?)", (import_id,))
        await db.execute("UPDATE imports SET status = 'queued' WHERE id = ?", (import_id,))
        await db.execute("DELETE FROM telegram_collections WHERE import_id = ?", (import_id,))
        await db.commit()
    return import_id


async def active_collection(owner_id, chat_id):
    async with upload_locks[owner_id]:
        async with get_db_connection() as db:
            return await one(db, "SELECT import_id FROM telegram_collections WHERE owner_id = ? AND chat_id = ?", (owner_id, chat_id))
