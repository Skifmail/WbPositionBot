"""Модуль конфигурации приложения.

Содержит настройки приложения, загружаемые из переменных окружения или .env файла.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Настройки приложения, загружаемые из переменных окружения.

    Использует Pydantic для валидации и управления конфигурацией.
    Настройки загружаются из файла .env или переменных окружения.

    Attributes:
        telegram_token: Токен Telegram бота для API.
        database_url: URL подключения к базе данных PostgreSQL.
        scheduler_enabled: Флаг включения автоматического планировщика.
        default_device: Устройство по умолчанию для поиска (pc/android/ios).
        webhook_url: URL для webhook режима (опционально).
        webhook_secret: Секретный токен для валидации webhook.
        app_host: Хост для запуска веб-сервера.
        app_port: Порт для запуска веб-сервера.
        cron_secret: Секретный токен для внешнего cron триггера.

    Example:
        >>> from app.config import settings
        >>> print(settings.telegram_token)
        '123456:ABC-DEF...'
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    telegram_token: str | None = Field(None, env="TELEGRAM_TOKEN")
    database_url: str | None = Field(None, env="DATABASE_URL")
    scheduler_enabled: bool = Field(True, env="SCHEDULER_ENABLED")
    default_device: str = Field("pc", env="DEFAULT_DEVICE")

    # Настройки для режима webhook
    webhook_enabled: bool = Field(True, env="WEBHOOK_ENABLED")
    webhook_url: str | None = Field(None, env="WEBHOOK_URL")
    webhook_secret: str | None = Field(None, env="WEBHOOK_SECRET")
    app_host: str = Field("0.0.0.0", env="APP_HOST")
    app_port: int = Field(8080, env="PORT")

    # Внешний cron триггер
    cron_secret: str | None = Field(None, env="CRON_SECRET")


# Глобальный экземпляр настроек
settings = Settings()
