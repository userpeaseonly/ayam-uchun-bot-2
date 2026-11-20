"""Create and verify a SQLite snapshot using the online backup API."""

import argparse
import asyncio
import os
from pathlib import Path
import tempfile

import config
from scripts.database.db import get_db_connection


async def backup_database(destination: Path, *, if_exists: bool = False):
    source = Path(config.DB_PATH)
    if not source.is_file():
        if if_exists:
            print("Database does not exist yet; no backup needed.")
            return
        raise FileNotFoundError("Source database does not exist")
    if source.resolve() == destination.resolve():
        raise ValueError("Backup destination must differ from the live database")
    if destination.exists():
        raise FileExistsError("Backup destination already exists")

    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".backup-", suffix=".sqlite3", dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        async with get_db_connection() as db:
            async with get_db_connection(temporary) as target:
                await db.backup(target)
                cursor = await target.execute("PRAGMA quick_check")
                rows = await cursor.fetchall()
                if [row[0] for row in rows] != ["ok"]:
                    raise RuntimeError("SQLite backup integrity check failed")
        # Link publishes the completed snapshot atomically without overwriting a file.
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Verified database backup: {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--if-exists", action="store_true")
    args = parser.parse_args()
    asyncio.run(backup_database(args.output, if_exists=args.if_exists))
