import asyncio
import logging
import sys
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TEST, PRODUCTION
from aiogram.enums import ParseMode

import config
from scripts.database.db import init_db
from handlers import common, admin, student, import_upload, payments, browser_auth

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
        session=AiohttpSession(api=TEST if config.TELEGRAM_TEST_ENVIRONMENT else PRODUCTION),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Include routers
    dp.include_router(payments.router)
    dp.include_router(browser_auth.router)
    dp.include_router(common.router)
    dp.include_router(import_upload.router)
    dp.include_router(admin.router)
    dp.include_router(student.router)

    logger.info("Starting bot polling...")
    from services.web_app import create_web_app
    from services.job_worker import recover_jobs, worker_loop
    app = create_web_app()
    runner = web.AppRunner(app, access_log=None)
    workers = []
    try:
        from services.web_app import BOT_USERNAME_KEY, PAYMENT_BOT_KEY
        app[PAYMENT_BOT_KEY] = bot
        app[BOT_USERNAME_KEY] = (await bot.get_me()).username
        await recover_jobs()
        await runner.setup()
        await web.TCPSite(runner, config.WEB_HOST, config.WEB_PORT).start()
        from services.stars_payments import payment_worker
        workers = [asyncio.create_task(payment_worker(bot)),
                   asyncio.create_task(worker_loop(bot, imports=True)),
                   asyncio.create_task(worker_loop(bot, timers=True)),
                   *[asyncio.create_task(worker_loop(bot)) for _ in range(config.GRADING_CONCURRENCY)]]
        if config.MINI_APP_URL:
            from aiogram.types import MenuButtonWebApp, WebAppInfo
            await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Testlar", web_app=WebAppInfo(url=config.MINI_APP_URL)))
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, close_bot_session=False)
    finally:
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
