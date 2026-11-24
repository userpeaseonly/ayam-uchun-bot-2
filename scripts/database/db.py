from contextlib import asynccontextmanager
import aiosqlite
import logging
import config

logger = logging.getLogger(__name__)


@asynccontextmanager
async def get_db_connection(db_path=None, *, timeout=60.0):
    async with aiosqlite.connect(db_path if db_path is not None else config.DB_PATH, timeout=timeout) as db:
        for statement in (
            f"PRAGMA busy_timeout = {max(0, int(timeout * 1000))};",
            "PRAGMA foreign_keys = ON;",
            "PRAGMA journal_mode = WAL;",
        ):
            # Finalize PRAGMA statements before callers use the connection,
            # including as an online-backup destination.
            async with db.execute(statement):
                pass
        db.row_factory = aiosqlite.Row
        yield db


async def init_db():
    async with get_db_connection() as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                total_questions INTEGER NOT NULL,
                open_questions_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP NULL
            );

            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id INTEGER NOT NULL,
                question_num INTEGER NOT NULL,
                question_type TEXT NOT NULL, -- 'closed' or 'open'
                correct_answer TEXT,         -- 'A', 'B', 'C', 'D'
                ai_instructions TEXT,        -- Prompt/rubric for open question
                assigned_tier TEXT,          -- 'easy', 'medium', 'hard', 'open'
                assigned_points REAL,        -- 1.1, 1.7, 2.5, or default open points
                correct_count INTEGER DEFAULT 0,
                FOREIGN KEY (test_id) REFERENCES tests(id) ON DELETE CASCADE,
                UNIQUE(test_id, question_num)
            );

            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                first_name TEXT,
                last_name TEXT,
                username TEXT,
                total_correct INTEGER DEFAULT 0,
                total_score REAL DEFAULT 0.0,
                rank INTEGER,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (test_id) REFERENCES tests(id) ON DELETE CASCADE,
                UNIQUE(test_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submission_id INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                user_answer TEXT NOT NULL,
                is_correct INTEGER NOT NULL DEFAULT 0,
                points_awarded REAL DEFAULT 0.0,
                ai_feedback TEXT,
                FOREIGN KEY (submission_id) REFERENCES submissions(id) ON DELETE CASCADE,
                FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE,
                UNIQUE(submission_id, question_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tests_code ON tests(code);
            CREATE INDEX IF NOT EXISTS idx_questions_test ON questions(test_id);
            CREATE INDEX IF NOT EXISTS idx_submissions_test ON submissions(test_id);
            CREATE INDEX IF NOT EXISTS idx_answers_sub ON answers(submission_id);
            """
        )
        await db.commit()
        from scripts.database.migrations import migrate
        await migrate(db)
        logger.info("Database initialized successfully.")
