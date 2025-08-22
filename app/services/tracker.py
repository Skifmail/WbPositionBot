from __future__ import annotations

from datetime import datetime
from typing import Iterable

from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import asyncio

from app.db.base import async_session_factory
from app.db.models import Tracking, Article, User
from app.services.wb_client import WBClient


async def fetch_position_for_phrase(client: WBClient, sku: int, phrase: str, device: str, dest: int) -> int | None:
	return await client.get_product_position(sku=sku, query=phrase, device=device, dest=dest)


async def _safe_send(bot: Bot, chat_id: int, text: str, *, attempts: int = 3) -> None:
	last_exc: Exception | None = None
	for i in range(attempts):
		try:
			await bot.send_message(chat_id=chat_id, text=text)
			return
		except (TelegramNetworkError, asyncio.TimeoutError) as exc:
			last_exc = exc
			delay = 0.5 * (2 ** i)
			await asyncio.sleep(delay)
		except Exception as exc:  # noqa: BLE001
			last_exc = exc
			break
	if last_exc:
		logger.warning(f"Failed to deliver notification to {chat_id}: {last_exc}")


async def process_user_trackings(session: AsyncSession, user: User, bot: Bot) -> None:
	if user.dest_code is None:
		logger.debug(f"Skip user {user.telegram_id}: no dest configured")
		return
	result = await session.execute(
		select(Article)
			.where(Article.user_id == user.id)
			.options(selectinload(Article.trackings))
	)
	articles: list[Article] = list(result.scalars().all())
	if not articles:
		return
	async with WBClient() as client:
		for article in articles:
			for tracking in list(article.trackings):
				if not tracking.enabled:
					continue
				pos = await fetch_position_for_phrase(client, article.sku, tracking.phrase, user.device, user.dest_code)
				tracking.last_checked_at = datetime.utcnow()
				tracking.last_position = pos
				if pos is not None and pos > tracking.threshold_position:
					if tracking.last_notified_position is None or pos != tracking.last_notified_position:
						text = (
							f"Артикул {article.sku} опустился до позиции {pos} по фразе “{tracking.phrase}”.\n"
							f"Порог: {tracking.threshold_position}. Устройство: {user.device}. Регион: {user.region_city or user.region_district}."
						)
						await _safe_send(bot, user.telegram_id, text)
						tracking.last_notified_position = pos
	# короткий статус после прохода
	region = user.region_city or user.region_district or "Не выбран"
	aut = "Включено" if user.auto_update_enabled else "Отключено"
	await _safe_send(bot, user.telegram_id, text=f"🔁 Автообновление выполнилось. ⚙️ {user.device} | 🗺️ {region} | {aut}")


async def run_hourly_tracking(bot: Bot) -> None:
	logger.info("Running scheduled tracking job")
	async with async_session_factory() as session:
		users = list((await session.execute(select(User))).scalars().all())
		for user in users:
			if not user.auto_update_enabled:
				continue
			try:
				await process_user_trackings(session, user, bot)
			except Exception as exc:  # noqa: BLE001
				logger.warning(f"Tracking for user {user.telegram_id} failed: {exc}")
		await session.commit()
