from __future__ import annotations

import asyncio
from typing import AsyncGenerator
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.config import settings


_ALLOWED_SSLMODE = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}


def _normalize_async_url(url: str) -> str:
	# Convert postgres:// to postgresql:// and enforce asyncpg driver
	if url.startswith("postgres://"):
		url = "postgresql://" + url[len("postgres://"):]
	if url.startswith("postgresql://") and "+asyncpg" not in url:
		url = "postgresql+asyncpg://" + url[len("postgresql://"):]
	# Rewrite query params for asyncpg
	parts = urlparse(url)
	qs = dict(parse_qsl(parts.query, keep_blank_values=True))
	# Drop unsupported/psql-specific params
	for key in ["channel_binding", "target_session_attrs"]:
		qs.pop(key, None)
	# Map sslmode -> ssl (asyncpg expects 'ssl')
	sslmode = qs.pop("sslmode", None)
	if sslmode:
		val = str(sslmode).lower()
		if val in _ALLOWED_SSLMODE:
			qs["ssl"] = val
	# For Neon ensure ssl=require if not set
	host = parts.hostname or ""
	if host.endswith("neon.tech") and "ssl" not in qs:
		qs["ssl"] = "require"
	new_query = urlencode(qs)
	return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))


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
		await conn.execute("CREATE SCHEMA IF NOT EXISTS wbpos")
		await conn.run_sync(Base.metadata.create_all)


def init_db_sync() -> None:
	asyncio.get_event_loop().run_until_complete(init_db())
