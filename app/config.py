from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
	"""Application settings loaded from environment variables."""

	model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

	telegram_token: str | None = Field(None, env="TELEGRAM_TOKEN")
	database_url: str | None = Field(None, env="DATABASE_URL")
	scheduler_enabled: bool = Field(True, env="SCHEDULER_ENABLED")
	default_device: str = Field("pc", env="DEFAULT_DEVICE")

	# Webhook mode
	webhook_url: str | None = Field(None, env="WEBHOOK_URL")
	webhook_secret: str | None = Field(None, env="WEBHOOK_SECRET")
	app_host: str = Field("0.0.0.0", env="APP_HOST")
	app_port: int = Field(8080, env="PORT")


settings = Settings()
