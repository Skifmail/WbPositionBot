from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
	"""Application settings loaded from environment variables."""

	model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

	telegram_token: str | None = Field(None, env="TELEGRAM_TOKEN")
	database_url: str = Field(
		"postgresql+asyncpg://postgres:postgres@localhost:5432/wb_bot",
		env="DATABASE_URL",
	)
	scheduler_enabled: bool = Field(True, env="SCHEDULER_ENABLED")
	default_device: str = Field("pc", env="DEFAULT_DEVICE")


settings = Settings()
