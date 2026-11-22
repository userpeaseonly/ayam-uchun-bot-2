"""Additive, transactional migrations preserve existing bot assessments."""

MIGRATIONS = [
    [
        "ALTER TABLE tests ADD COLUMN document_json TEXT",
        "ALTER TABLE tests ADD COLUMN source_import_id TEXT",
        "ALTER TABLE questions ADD COLUMN content_json TEXT",
        "ALTER TABLE answers ADD COLUMN grading_status TEXT NOT NULL DEFAULT 'done'",
        """CREATE TABLE imports (
            id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL, title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued', progress INTEGER NOT NULL DEFAULT 0,
            document_json TEXT, error TEXT, revision INTEGER NOT NULL DEFAULT 0,
            published_test_id INTEGER REFERENCES tests(id),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE assets (
            id TEXT PRIMARY KEY, import_id TEXT NOT NULL REFERENCES imports(id),
            kind TEXT NOT NULL, filename TEXT NOT NULL, mime TEXT NOT NULL,
            page INTEGER, text_content TEXT, original_name TEXT
        )""",
        """CREATE TABLE jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
            target TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
            attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL DEFAULT 0,
            error TEXT, UNIQUE(kind, target)
        )""",
        "CREATE INDEX idx_jobs_ready ON jobs(status, available_at)",
        "CREATE INDEX idx_assets_import ON assets(import_id, kind, page)",
        """CREATE TABLE answer_drafts (
            test_id INTEGER NOT NULL REFERENCES tests(id), user_id INTEGER NOT NULL,
            answers_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(test_id, user_id)
        )""",
        """CREATE TABLE import_chunks (
            import_id TEXT NOT NULL REFERENCES imports(id), chunk INTEGER NOT NULL,
            result_json TEXT NOT NULL, PRIMARY KEY(import_id, chunk)
        )""",
    ],
    [
        "ALTER TABLE assets ADD COLUMN source_size INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE assets ADD COLUMN source_order INTEGER",
        """CREATE TABLE telegram_uploads (
            chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
            owner_id INTEGER NOT NULL, import_id TEXT NOT NULL REFERENCES imports(id),
            PRIMARY KEY(chat_id, message_id)
        )""",
        """CREATE TABLE telegram_collections (
            chat_id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL,
            import_id TEXT NOT NULL UNIQUE REFERENCES imports(id)
        )""",
    ],
]


async def migrate(db):
    await db.execute("BEGIN IMMEDIATE")
    try:
        await db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)")
        cursor = await db.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
        version = (await cursor.fetchone())[0]
        if version > len(MIGRATIONS):
            raise RuntimeError("Database schema is newer than this application")
        for index, statements in enumerate(MIGRATIONS, 1):
            if index > version:
                for statement in statements:
                    await db.execute(statement)
                await db.execute("INSERT INTO schema_migrations VALUES (?)", (index,))
        await db.commit()
    except BaseException:
        await db.rollback()
        raise
