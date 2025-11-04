"""Скрипт для очистки и пересоздания схемы БД wbpos."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from time import sleep

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Добавляем корень проекта в sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402


async def _drop_create_schema(engine_url: str) -> None:
    """Удаляет и создаёт схему wbpos в PostgreSQL.

    Args:
        engine_url: URL подключения к БД.
    """
    engine = create_async_engine(engine_url, echo=False, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS wbpos CASCADE"))
        await conn.execute(text("CREATE SCHEMA wbpos"))
    await engine.dispose()


async def reset_schema(retries: int = 3) -> None:
    """Пересоздаёт схему wbpos с повтором при сбоях.

    Args:
        retries: Количество попыток при ошибках.

    Raises:
        Exception: Если все попытки неудачны.
    """
    logger.warning("Dropping schema wbpos CASCADE and recreating...")
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            await _drop_create_schema(settings.database_url)
            logger.success("Schema wbpos recreated.")
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.error(f"Attempt {attempt} failed: {exc}")
            sleep(1.0 * attempt)
    if last_exc:
        raise last_exc


if __name__ == "__main__":
    asyncio.run(reset_schema())
