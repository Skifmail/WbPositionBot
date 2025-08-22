from __future__ import annotations

import asyncio
from typing import AsyncGenerator
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.config import settings


def _normalize_async_url(url: str) -> str:
	# Convert postgres:// to postgresql:// and enforce asyncpg driver
	if url.startswith("postgres://"):
		url = "postgresql://" + url[len("postgres://"):]
	if url.startswith("postgresql://") and "+asyncpg" not in url:
		url = "postgresql+asyncpg://" + url[len("postgresql://"):]
	# Rewrite sslmode=require -> ssl=true for asyncpg
	parts = urlparse(url)
	qs = dict(parse_qsl(parts.query, keep_blank_values=True))
	if "sslmode" in qs:
		# asyncpg expects 'ssl' flag; map require/require* to true
		if qs.get("sslmode", "").lower() in {"require", "required", "verify-full", "verify_ca", "verify-full"}:
			qs["ssl"] = "true"
		qs.pop("sslmode", None)
	# Some providers include 'sslmode=require' implicitly; for neon host enforce ssl=true if not set
	if parts.hostname and parts.hostname.endswith("neon.tech") and "ssl" not in qs:
		qs["ssl"] = "true"
	new_query = urlencode(qs)
	url = urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))
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
