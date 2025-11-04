"""Главный модуль Telegram-бота для отслеживания позиций товаров Wildberries.

Этот модуль предоставляет точку входа для запуска бота в режиме polling или webhook.
Бот позволяет пользователям отслеживать позиции своих товаров на Wildberries
по поисковым запросам с настройкой региона и типа устройства.
"""

import asyncio
from functools import partial
from urllib.parse import urlparse
import re
import secrets
import string

from aiohttp import web
from loguru import logger
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler

from app.config import settings
from app.db.base import init_db
from app.handlers.start import router as start_router
from app.handlers.articles import router as articles_router
from app.handlers.settings import router as settings_router
from app.handlers.manual_check import router as manual_router
from app.handlers.tracking import router as tracking_router
from app.scheduler import setup_scheduler, shutdown_scheduler
from app.services.tracker import run_hourly_tracking


# Регулярное выражение для валидации секретного токена webhook
_ALLOWED_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
# Допустимые символы для генерации секретного токена
_ALLOWED_SECRET_CHARS = string.ascii_letters + string.digits + "_-"


def _normalize_secret_token(raw_secret: str | None) -> str | None:
    """Валидирует и нормализует секретный токен для webhook Telegram.

    Telegram требует, чтобы секретный токен содержал только символы A-Z, a-z, 0-9,
    '_' и '-' и имел длину от 1 до 256 символов. Если переданный токен невалиден,
    функция генерирует безопасный случайный токен.

    Args:
        raw_secret: Исходная строка секретного токена или None.

    Returns:
        Валидированный токен, если он корректен; новый сгенерированный токен,
        если исходный невалиден; None, если токен не был передан.

    Raises:
        Функция не выбрасывает исключений.

    Example:
        >>> _normalize_secret_token("valid_token-123")
        'valid_token-123'
        >>> _normalize_secret_token(None)
        None
    """
    if not raw_secret:
        return None
    if _ALLOWED_SECRET_RE.match(raw_secret):
        return raw_secret
    logger.warning(
        "WEBHOOK_SECRET содержит недопустимые символы. "
        "Будет сгенерирован безопасный токен."
    )
    return "".join(secrets.choice(_ALLOWED_SECRET_CHARS) for _ in range(48))


def build_dispatcher() -> Dispatcher:
    """Создаёт и настраивает диспетчер бота со всеми роутерами.

    Инициализирует диспетчер с хранилищем в памяти и регистрирует все
    обработчики команд и сообщений в правильном порядке.

    Returns:
        Настроенный экземпляр Dispatcher со всеми подключёнными роутерами.

    Example:
        >>> dp = build_dispatcher()
        >>> # диспетчер готов к обработке сообщений
    """
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(start_router)
    dp.include_router(articles_router)
    dp.include_router(tracking_router)
    dp.include_router(settings_router)
    dp.include_router(manual_router)
    return dp


async def start_polling_mode() -> None:
    """Запускает бота в режиме polling (опрос сервера Telegram).

    Инициализирует базу данных, создаёт экземпляр бота, настраивает планировщик
    (если включён) и начинает опрос обновлений от Telegram. Обрабатывает
    корректное завершение работы при прерывании.

    Raises:
        RuntimeError: Если переменная окружения TELEGRAM_TOKEN не установлена.

    Example:
        >>> await start_polling_mode()  # doctest: +SKIP
        # Бот начинает опрос сообщений
    """
    logger.add("bot.log", rotation="10 MB")
    await init_db()
    if not settings.telegram_token:
        raise RuntimeError("TELEGRAM_TOKEN не задан")
    bot = Bot(
        token=settings.telegram_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = build_dispatcher()
    if settings.scheduler_enabled:
        await setup_scheduler(bot)
    logger.info("Запуск бота в режиме polling")
    try:
        await dp.start_polling(bot)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Получен сигнал остановки")
    finally:
        await shutdown_scheduler()
        try:
            await bot.session.close()
        except Exception:
            pass
        logger.info("Бот остановлен")


async def on_startup(
    app: web.Application,
    bot: Bot,
    dp: Dispatcher,
    secret_token: str | None
) -> None:
    """Обработчик запуска веб-приложения в режиме webhook.

    Инициализирует базу данных, настраивает планировщик и устанавливает
    webhook для получения обновлений от Telegram.

    Args:
        app: Экземпляр aiohttp веб-приложения.
        bot: Экземпляр Telegram бота.
        dp: Диспетчер для обработки обновлений.
        secret_token: Секретный токен для валидации webhook запросов.

    Raises:
        RuntimeError: Если переменная окружения WEBHOOK_URL не установлена.
    """
    await init_db()
    if settings.scheduler_enabled:
        await setup_scheduler(bot)
    if not settings.webhook_url:
        raise RuntimeError("WEBHOOK_URL не задан")
    await bot.set_webhook(
        url=settings.webhook_url,
        secret_token=secret_token,
        drop_pending_updates=True
    )
    logger.info("Webhook установлен: {}", settings.webhook_url)


async def on_cleanup(app: web.Application, bot: Bot) -> None:
    """Обработчик завершения работы веб-приложения.

    Останавливает планировщик, удаляет webhook и закрывает сессию бота.

    Args:
        app: Экземпляр aiohttp веб-приложения.
        bot: Экземпляр Telegram бота.
    """
    await shutdown_scheduler()
    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception:
        pass
    try:
        await bot.session.close()
    except Exception:
        pass
    logger.info("Бот остановлен")


def healthcheck(_: web.Request) -> web.Response:
    """Обработчик health-check эндпоинта.

    Args:
        _: HTTP запрос (не используется).

    Returns:
        HTTP ответ со статусом 200 и текстом "ok".
    """
    return web.Response(text="ok")


async def cron_handler(request: web.Request) -> web.Response:
    """Обработчик внешнего cron-триггера для запуска отслеживания.

    Позволяет внешним системам (например, Render Cron Jobs) запускать
    задачу отслеживания позиций через HTTP запрос с защитой секретным токеном.

    Args:
        request: HTTP запрос с query параметром 's' для авторизации.

    Returns:
        HTTP ответ со статусом 200 при успехе или 403 при неверном токене.

    Example:
        GET /cron?s=secret_token
    """
    secret = request.query.get("s")
    if settings.cron_secret and secret != settings.cron_secret:
        return web.Response(status=403, text="forbidden")
    # Запускаем отслеживание немедленно
    bot: Bot = request.app["bot"]
    asyncio.create_task(run_hourly_tracking(bot))
    return web.Response(text="ok")


def run_webhook_server() -> None:
    """Запускает бота в режиме webhook сервера.

    Создаёт aiohttp веб-сервер для приёма обновлений от Telegram через webhook.
    Дополнительно предоставляет эндпоинты для health-check и внешнего cron.

    Raises:
        RuntimeError: Если переменная окружения TELEGRAM_TOKEN не установлена.

    Example:
        >>> run_webhook_server()  # doctest: +SKIP
        # Сервер запущен на 0.0.0.0:8080
    """
    logger.add("bot.log", rotation="10 MB")
    if not settings.telegram_token:
        raise RuntimeError("TELEGRAM_TOKEN не задан")
    bot = Bot(
        token=settings.telegram_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = build_dispatcher()
    app = web.Application()
    # Определяем путь webhook из WEBHOOK_URL
    path = urlparse(settings.webhook_url or "/webhook").path or "/webhook"
    secret_token = _normalize_secret_token(settings.webhook_secret)
    handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=secret_token
    )
    handler.register(app, path)
    app["bot"] = bot
    app.router.add_get("/health", healthcheck)
    app.router.add_get("/cron", cron_handler)
    app.on_startup.append(
        partial(on_startup, bot=bot, dp=dp, secret_token=secret_token)
    )
    app.on_cleanup.append(partial(on_cleanup, bot=bot))
    logger.info(
        "Запуск webhook сервера на {}:{} (путь: {})",
        settings.app_host,
        settings.app_port,
        path
    )
    web.run_app(app, host=settings.app_host, port=settings.app_port)


if __name__ == "__main__":
    try:
        if settings.webhook_enabled and settings.webhook_url:
            run_webhook_server()
        else:
            asyncio.run(start_polling_mode())
    except KeyboardInterrupt:
        logger.info("Прервано пользователем")
