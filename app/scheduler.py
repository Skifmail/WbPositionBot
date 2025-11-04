"""Модуль планировщика задач для автоматического отслеживания позиций.

Обеспечивает периодический запуск задачи отслеживания позиций товаров
на Wildberries для всех пользователей с включённым автообновлением.
"""

from __future__ import annotations

from typing import Optional

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from app.config import settings
from app.services.tracker import run_hourly_tracking

# Глобальный экземпляр планировщика
_scheduler: Optional[AsyncIOScheduler] = None


async def setup_scheduler(bot: Bot) -> None:
    """Инициализирует и запускает планировщик задач.

    Создаёт задачу для периодического (каждые 10 минут) запуска отслеживания
    позиций товаров. Если планировщик отключён в настройках, функция ничего не делает.

    Args:
        bot: Экземпляр Telegram бота для отправки уведомлений.

    Example:
        >>> await setup_scheduler(bot)  # doctest: +SKIP
        # Планировщик запущен, задача отслеживания зарегистрирована
    """
    global _scheduler
    if not settings.scheduler_enabled:
        logger.info("Планировщик отключён в настройках")
        return
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
        _scheduler.add_job(
            run_hourly_tracking,
            "interval",
            minutes=10,
            kwargs={"bot": bot},
            id="tracking_10min",
            replace_existing=True
        )
        _scheduler.start()
        logger.info("Планировщик запущен: задача отслеживания каждые 10 минут")


async def shutdown_scheduler() -> None:
    """Останавливает планировщик задач и освобождает ресурсы.

    Корректно завершает работу планировщика без ожидания завершения текущих задач.
    Обрабатывает возможные ошибки при остановке.

    Example:
        >>> await shutdown_scheduler()  # doctest: +SKIP
        # Планировщик остановлен
    """
    global _scheduler
    if _scheduler:
        try:
            _scheduler.shutdown(wait=False)
            logger.info("Планировщик остановлен")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Не удалось остановить планировщик: {exc}")
        finally:
            _scheduler = None
