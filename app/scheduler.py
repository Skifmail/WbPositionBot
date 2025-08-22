from __future__ import annotations

from typing import Optional

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from app.config import settings
from app.services.tracker import run_hourly_tracking

_scheduler: Optional[AsyncIOScheduler] = None


async def setup_scheduler(bot: Bot) -> None:
	global _scheduler
	if not settings.scheduler_enabled:
		logger.info("Scheduler disabled by settings")
		return
	if _scheduler is None:
		_scheduler = AsyncIOScheduler()
		_scheduler.add_job(run_hourly_tracking, "interval", minutes=10, kwargs={"bot": bot}, id="tracking_10min", replace_existing=True)
		_scheduler.start()
		logger.info("Scheduler started: 10-min tracking job registered")


async def shutdown_scheduler() -> None:
	global _scheduler
	if _scheduler:
		try:
			_scheduler.shutdown(wait=False)
			logger.info("Scheduler stopped")
		except Exception as exc:  # noqa: BLE001
			logger.warning(f"Failed to stop scheduler: {exc}")
		finally:
			_scheduler = None
