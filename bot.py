import asyncio
from loguru import logger
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties

from app.config import settings
from app.db.base import init_db
from app.handlers.start import router as start_router
from app.handlers.articles import router as articles_router
from app.handlers.settings import router as settings_router
from app.handlers.manual_check import router as manual_router
from app.handlers.tracking import router as tracking_router
from app.scheduler import setup_scheduler, shutdown_scheduler


async def main() -> None:
	logger.add("bot.log", rotation="10 MB")
	await init_db()
	if not settings.telegram_token:
		raise RuntimeError("TELEGRAM_TOKEN не задан в .env")
	bot = Bot(token=settings.telegram_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
	dp = Dispatcher(storage=MemoryStorage())
	dp.include_router(start_router)
	dp.include_router(articles_router)
	dp.include_router(tracking_router)
	dp.include_router(settings_router)
	dp.include_router(manual_router)
	await setup_scheduler(bot)
	logger.info("Starting polling")
	try:
		await dp.start_polling(bot)
	except (asyncio.CancelledError, KeyboardInterrupt):
		logger.info("Shutdown signal received")
	finally:
		await shutdown_scheduler()
		try:
			await bot.session.close()
		except Exception:
			pass
		logger.info("Bot stopped")


if __name__ == "__main__":
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		logger.info("Interrupted by user")
