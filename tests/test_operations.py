from pathlib import Path

import pytest

import config
from scripts.database.db import get_db_connection
from scripts.backup_db import backup_database
from scripts.run_bot import validate_configuration


@pytest.mark.asyncio
async def test_backup_captures_committed_wal_data(tmp_path, monkeypatch):
    live_db = tmp_path / "live.sqlite3"
    snapshot = tmp_path / "backups" / "snapshot.sqlite3"
    monkeypatch.setattr(config, "DB_PATH", str(live_db))

    async with get_db_connection() as db:
        await db.execute("CREATE TABLE sample (value TEXT)")
        await db.execute("INSERT INTO sample VALUES ('accepted answer')")
        await db.commit()
        assert Path(str(live_db) + "-wal").is_file()
        await backup_database(snapshot)
        # Later writes must not change the completed snapshot.
        await db.execute("INSERT INTO sample VALUES ('later answer')")
        await db.commit()

    async with get_db_connection(snapshot) as db:
        cursor = await db.execute("SELECT value FROM sample")
        assert [row[0] for row in await cursor.fetchall()] == ["accepted answer"]
    assert not list(snapshot.parent.glob(".backup-*"))


@pytest.mark.asyncio
async def test_backup_refuses_live_or_existing_destination(tmp_path, monkeypatch):
    live_db = tmp_path / "live.sqlite3"
    monkeypatch.setattr(config, "DB_PATH", str(live_db))
    async with get_db_connection() as db:
        await db.execute("CREATE TABLE sample (value TEXT)")
        await db.commit()
    with pytest.raises(ValueError, match="live database"):
        await backup_database(live_db)
    existing = tmp_path / "existing.sqlite3"
    existing.write_bytes(b"keep this backup")
    with pytest.raises(FileExistsError):
        await backup_database(existing)
    assert existing.read_bytes() == b"keep this backup"


@pytest.mark.asyncio
async def test_backup_does_not_create_missing_source(tmp_path, monkeypatch):
    live_db = tmp_path / "missing.sqlite3"
    snapshot = tmp_path / "snapshot.sqlite3"
    monkeypatch.setattr(config, "DB_PATH", str(live_db))
    await backup_database(snapshot, if_exists=True)
    with pytest.raises(FileNotFoundError):
        await backup_database(snapshot)
    assert not live_db.exists()
    assert not snapshot.exists()


def test_container_requires_configured_ai_provider(monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "123:example")
    monkeypatch.setattr(config, "ADMIN_IDS", [123])
    monkeypatch.setattr(config, "AI_PROVIDER", "deepseek")
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "another-provider-key")
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        validate_configuration()
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "configured-key")
    validate_configuration()
