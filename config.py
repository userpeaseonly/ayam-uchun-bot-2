import os
from typing import List
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

# Parse admin IDs from comma-separated string
admin_ids_raw: str = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: List[int] = [
    int(x.strip()) for x in admin_ids_raw.split(",") if x.strip().isdigit()
]

# AI Provider configurations
AI_PROVIDER: str = os.getenv("AI_PROVIDER", "deepseek").lower()

# DeepSeek settings
DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
DEEPSEEK_IMPORT_MODEL: str = os.getenv("DEEPSEEK_IMPORT_MODEL", "deepseek-flash")
AI_IMPORT_TIMEOUT: int = int(os.getenv("AI_IMPORT_TIMEOUT", "180"))
AI_GRADING_TIMEOUT: int = int(os.getenv("AI_GRADING_TIMEOUT", "60"))
GRADING_CONCURRENCY: int = max(1, min(16, int(os.getenv("GRADING_CONCURRENCY", "8"))))

# Gemini settings (optional fallback)
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

# Storage & Point settings
DB_PATH: str = os.getenv("DB_PATH", "bot_database.sqlite3")
LOG_FILE: str = os.getenv("LOG_FILE", "bot.log")
DEFAULT_OPEN_QUESTION_POINTS: float = float(os.getenv("DEFAULT_OPEN_QUESTION_POINTS", "2.5"))

# Same-origin Mini App API. Leave URL empty to retain bot-only operation.
MINI_APP_URL: str = os.getenv("MINI_APP_URL", "").rstrip("/")
WEB_HOST: str = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT: int = int(os.getenv("WEB_PORT", "8080"))
MEDIA_PATH: str = os.getenv("MEDIA_PATH", "data/media")
FRONTEND_PATH: str = os.getenv("FRONTEND_PATH", "web/dist")
MAX_UPLOAD_BYTES: int = 20 * 1024 * 1024
MAX_IMPORT_PAGES: int = 30
TELEGRAM_AUTH_MAX_AGE: int = 3600

# Scoring tiers for closed questions
TIER_EASY_POINTS: float = 1.1
TIER_MEDIUM_POINTS: float = 1.7
TIER_HARD_POINTS: float = 2.5
