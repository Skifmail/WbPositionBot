"""Модуль базовой настройки подключения к базе данных.

Настраивает асинхронное подключение к PostgreSQL через SQLAlchemy с использованием
драйвера asyncpg. Обрабатывает различные форматы DATABASE_URL и специфичные
настройки для разных провайдеров (Render, Neon и т.д.).
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy import text

from app.config import settings


# Допустимые режимы SSL для PostgreSQL
_ALLOWED_SSLMODE = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}


def _normalize_async_url(url: str) -> str:
    """Нормализует URL базы данных для работы с asyncpg драйвером.

    Преобразует различные форматы URL (postgres://, postgresql://) в формат,
    совместимый с asyncpg. Удаляет неподдерживаемые параметры и настраивает
    SSL для специфичных провайдеров.

    Args:
        url: Исходный URL подключения к базе данных.

    Returns:
        Нормализованный URL для asyncpg.

    Example:
        >>> _normalize_async_url("postgres://user:pass@host/db")  # doctest: +SKIP
        'postgresql+asyncpg://user:pass@host/db?ssl=require'
    """
    # Преобразуем postgres:// в postgresql:// и добавляем драйвер asyncpg
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    
    # Обрабатываем query параметры для asyncpg
    parts = urlparse(url)
    qs = dict(parse_qsl(parts.query, keep_blank_values=True))
    
    # Удаляем неподдерживаемые/специфичные для psql параметры
    for key in ["channel_binding", "target_session_attrs"]:
        qs.pop(key, None)
    
    # Преобразуем sslmode -> ssl (asyncpg ожидает 'ssl')
    sslmode = qs.pop("sslmode", None)
    if sslmode:
        val = str(sslmode).lower()
        if val in _ALLOWED_SSLMODE:
            qs["ssl"] = val
    
    # Для Neon устанавливаем ssl=require по умолчанию
    host = parts.hostname or ""
    if host.endswith("neon.tech") and "ssl" not in qs:
        qs["ssl"] = "require"
    
    new_query = urlencode(qs)
    return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))


# Базовый класс для декларативных моделей SQLAlchemy
Base = declarative_base()

# Проверяем наличие DATABASE_URL в настройках
if not settings.database_url:
    raise RuntimeError(
        "DATABASE_URL не задан. Установите переменную окружения или "
        "настройте Render/Neon DATABASE_URL."
    )

# Создаём асинхронный движок базы данных
_async_db_url = _normalize_async_url(settings.database_url)
engine = create_async_engine(_async_db_url, echo=False, pool_pre_ping=True)

# Фабрика для создания асинхронных сессий
async_session_factory = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Генератор асинхронных сессий базы данных.

    Используется для dependency injection в обработчиках.

    Yields:
        AsyncSession: Асинхронная сессия базы данных.

    Example:
        >>> async for session in get_session():  # doctest: +SKIP
        ...     user = await session.get(User, 1)
    """
    async with async_session_factory() as session:
        yield session


async def init_db() -> None:
    """Инициализирует схему базы данных.

    Создаёт схему 'wbpos' (если не существует) и все таблицы,
    определённые в моделях.

    Example:
        >>> await init_db()  # doctest: +SKIP
        # База данных инициализирована
    """
    from app.db import models  # noqa: F401  # импортируем модели для регистрации
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS wbpos"))
        await conn.run_sync(Base.metadata.create_all)


def init_db_sync() -> None:
    """Синхронная обёртка для init_db().

    Запускает инициализацию базы данных в синхронном контексте.

    Example:
        >>> init_db_sync()  # doctest: +SKIP
        # База данных инициализирована синхронно
    """
    asyncio.get_event_loop().run_until_complete(init_db())
