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
DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# Gemini settings (optional fallback)
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

# Storage & Point settings
DB_PATH: str = os.getenv("DB_PATH", "bot_database.sqlite3")
LOG_FILE: str = os.getenv("LOG_FILE", "bot.log")
DEFAULT_OPEN_QUESTION_POINTS: float = float(os.getenv("DEFAULT_OPEN_QUESTION_POINTS", "2.5"))

# Scoring tiers for closed questions
TIER_EASY_POINTS: float = 1.1
TIER_MEDIUM_POINTS: float = 1.7
TIER_HARD_POINTS: float = 2.5
