from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.config import settings


def _normalize_async_url(url: str) -> str:
	# Convert postgres:// to postgresql:// and enforce asyncpg driver
	orig = url
	if url.startswith("postgres://"):
		url = "postgresql://" + url[len("postgres://"):]
	if url.startswith("postgresql://") and "+asyncpg" not in url:
		url = "postgresql+asyncpg://" + url[len("postgresql://"):]
	return url


Base = declarative_base()
if not settings.database_url:
	raise RuntimeError("DATABASE_URL не задан. Установите переменную окружения или настройте Render/Neon DATABASE_URL.")
_async_db_url = _normalize_async_url(settings.database_url)
engine = create_async_engine(_async_db_url, echo=False, pool_pre_ping=True)
async_session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
	async with async_session_factory() as session:
		yield session


async def init_db() -> None:
	"""Create database schema if not exists."""
	from app.db import models  # noqa: F401  # ensure models are imported
	async with engine.begin() as conn:
		# create schema wbpos if not exists
		await conn.execute("CREATE SCHEMA IF NOT EXISTS wbpos")
		await conn.run_sync(Base.metadata.create_all)


def init_db_sync() -> None:
	asyncio.get_event_loop().run_until_complete(init_db())
