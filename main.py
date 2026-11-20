import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import config
from scripts.database.db import init_db
from handlers import common, admin, student

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        *([logging.FileHandler(config.LOG_FILE, encoding="utf-8")] if config.LOG_FILE else []),
    ],
)
logger = logging.getLogger(__name__)


async def main():
    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN is not configured! Please set BOT_TOKEN in .env")
        print("\n[!] DIQQAT: .env faylida BOT_TOKEN ko'rsatilmagan. Iltimos, .env faylini to'ldiring.\n")
        return

    logger.info("Initializing database...")
    await init_db()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Include routers
    dp.include_router(common.router)
    dp.include_router(admin.router)
    dp.include_router(student.router)

    logger.info("Starting bot polling...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
