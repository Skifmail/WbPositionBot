import asyncio
from functools import partial
from urllib.parse import urlparse

from aiohttp import web
from loguru import logger
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler

from app.config import settings
from app.db.base import init_db
from app.handlers.start import router as start_router
from app.handlers.articles import router as articles_router
from app.handlers.settings import router as settings_router
from app.handlers.manual_check import router as manual_router
from app.handlers.tracking import router as tracking_router
from app.scheduler import setup_scheduler, shutdown_scheduler


def build_dispatcher() -> Dispatcher:
	"""Create dispatcher with all routers included."""
	dp = Dispatcher(storage=MemoryStorage())
	dp.include_router(start_router)
	dp.include_router(articles_router)
	dp.include_router(tracking_router)
	dp.include_router(settings_router)
	dp.include_router(manual_router)
	return dp


async def start_polling_mode() -> None:
	logger.add("bot.log", rotation="10 MB")
	await init_db()
	if not settings.telegram_token:
		raise RuntimeError("TELEGRAM_TOKEN не задан")
	bot = Bot(token=settings.telegram_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
	dp = build_dispatcher()
	if settings.scheduler_enabled:
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


async def on_startup(app: web.Application, bot: Bot, dp: Dispatcher) -> None:
	await init_db()
	if settings.scheduler_enabled:
		await setup_scheduler(bot)
	if not settings.webhook_url:
		raise RuntimeError("WEBHOOK_URL не задан")
	await bot.set_webhook(url=settings.webhook_url, secret_token=settings.webhook_secret or None, drop_pending_updates=True)
	logger.info("Webhook set: {}", settings.webhook_url)


async def on_cleanup(app: web.Application, bot: Bot) -> None:
	await shutdown_scheduler()
	try:
		await bot.delete_webhook(drop_pending_updates=False)
	except Exception:
		pass
	try:
		await bot.session.close()
	except Exception:
		pass
	logger.info("Bot stopped")


def healthcheck(_: web.Request) -> web.Response:
	return web.Response(text="ok")


def run_webhook_server() -> None:
	logger.add("bot.log", rotation="10 MB")
	if not settings.telegram_token:
		raise RuntimeError("TELEGRAM_TOKEN не задан")
	bot = Bot(token=settings.telegram_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
	dp = build_dispatcher()
	app = web.Application()
	# Determine webhook path from WEBHOOK_URL
	path = urlparse(settings.webhook_url or "/webhook").path or "/webhook"
	handler = SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=settings.webhook_secret or None)
	handler.register(app, path)
	app.router.add_get("/health", healthcheck)
	app.on_startup.append(partial(on_startup, bot=bot, dp=dp))
	app.on_cleanup.append(partial(on_cleanup, bot=bot))
	logger.info("Starting webhook server on {}:{} (path: {})", settings.app_host, settings.app_port, path)
	web.run_app(app, host=settings.app_host, port=settings.app_port)


if __name__ == "__main__":
	try:
		if settings.webhook_url:
			run_webhook_server()
		else:
			asyncio.run(start_polling_mode())
	except KeyboardInterrupt:
		logger.info("Interrupted by user")
