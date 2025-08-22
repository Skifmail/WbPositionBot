from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy import text

from app.config import settings


Base = declarative_base()
if not settings.database_url:
	raise RuntimeError("DATABASE_URL не задан. Установите переменную окружения или настройте Render DATABASE_URL.")
engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
async_session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
	async with async_session_factory() as session:
		yield session


async def init_db() -> None:
	"""Create database schema if not exists."""
	from app.db import models  # noqa: F401  # ensure models are imported
	async with engine.begin() as conn:
		# create schema wbpos if not exists
		await conn.execute(text("CREATE SCHEMA IF NOT EXISTS wbpos"))
		await conn.run_sync(Base.metadata.create_all)


def init_db_sync() -> None:
	asyncio.get_event_loop().run_until_complete(init_db())
