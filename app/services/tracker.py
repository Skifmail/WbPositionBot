"""Модуль автоматического отслеживания позиций товаров.

Обеспечивает периодическую проверку позиций всех отслеживаемых товаров
пользователей и отправку уведомлений при превышении пороговых значений.
"""

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


async def fetch_position_for_phrase(
    client: WBClient,
    sku: int,
    phrase: str,
    device: str,
    dest: int
) -> int | None:
    """Запрашивает позицию товара по поисковой фразе.

    Args:
        client: Клиент Wildberries API.
        sku: Артикул товара.
        phrase: Поисковая фраза.
        device: Тип устройства (pc/android/ios).
        dest: Код региона Wildberries.

    Returns:
        Позиция товара (нумерация с 1) или None, если не найден.
    """
    return await client.get_product_position(
        sku=sku,
        query=phrase,
        device=device,
        dest=dest
    )


async def _safe_send(
    bot: Bot,
    chat_id: int,
    text: str,
    *,
    attempts: int = 3
) -> None:
    """Безопасно отправляет сообщение пользователю с повторными попытками.

    При сбое сети автоматически повторяет отправку с экспоненциальной задержкой.

    Args:
        bot: Экземпляр Telegram бота.
        chat_id: ID чата для отправки сообщения.
        text: Текст сообщения.
        attempts: Количество попыток отправки (по умолчанию 3).
    """
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
        logger.warning(
            f"Не удалось доставить уведомление пользователю {chat_id}: {last_exc}"
        )


async def process_user_trackings(
    session: AsyncSession,
    user: User,
    bot: Bot
) -> None:
    """Обрабатывает отслеживание позиций для одного пользователя.

    Проверяет позиции всех артикулов пользователя по всем активным фразам.
    Отправляет уведомления, если позиция превышает пороговое значение.

    Args:
        session: Сессия базы данных.
        user: Пользователь для обработки.
        bot: Экземпляр Telegram бота для отправки уведомлений.
    """
    if user.dest_code is None:
        logger.debug(
            f"Пропускаем пользователя {user.telegram_id}: регион не настроен"
        )
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
                
                pos = await fetch_position_for_phrase(
                    client,
                    article.sku,
                    tracking.phrase,
                    user.device,
                    user.dest_code
                )
                tracking.last_checked_at = datetime.utcnow()
                tracking.last_position = pos
                
                # Отправляем уведомление, если позиция хуже порога
                if pos is not None and pos > tracking.threshold_position:
                    # Проверяем, что это новая позиция (чтобы не спамить)
                    if (tracking.last_notified_position is None or 
                        pos != tracking.last_notified_position):
                        text = (
                            f"Артикул {article.sku} опустился до позиции {pos} "
                            f"по фразе «{tracking.phrase}».\n"
                            f"Порог: {tracking.threshold_position}. "
                            f"Устройство: {user.device}. "
                            f"Регион: {user.region_city or user.region_district}."
                        )
                        await _safe_send(bot, user.telegram_id, text)
                        tracking.last_notified_position = pos
    
    # Краткий статус после завершения проверки
    region = user.region_city or user.region_district or "Не выбран"
    status = "Включено" if user.auto_update_enabled else "Отключено"
    await _safe_send(
        bot,
        user.telegram_id,
        text=f"🔁 Автообновление выполнилось. ⚙️ {user.device} | 🗺️ {region} | {status}"
    )


async def run_hourly_tracking(bot: Bot) -> None:
    """Запускает задачу отслеживания для всех пользователей.

    Выполняется планировщиком каждые 10 минут. Проверяет позиции товаров
    для всех пользователей с включённым автообновлением.

    Args:
        bot: Экземпляр Telegram бота для отправки уведомлений.

    Example:
        >>> await run_hourly_tracking(bot)  # doctest: +SKIP
        # Отслеживание выполнено для всех пользователей
    """
    logger.info("Запуск задачи планового отслеживания")
    async with async_session_factory() as session:
        users = list((await session.execute(select(User))).scalars().all())
        for user in users:
            if not user.auto_update_enabled:
                continue
            try:
                await process_user_trackings(session, user, bot)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    f"Отслеживание для пользователя {user.telegram_id} не удалось: {exc}"
                )
        await session.commit()
