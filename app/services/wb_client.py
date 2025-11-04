"""Клиент для работы с публичными API Wildberries.

Предоставляет методы для поиска товаров, получения информации о товаре
и загрузки изображений с использованием кэширования и retry логики.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional, Tuple, Callable

import aiohttp
from aiohttp import ClientConnectorError
from loguru import logger

# URL эндпоинтов API Wildberries
WB_SEARCH_URL = "https://search.wb.ru/exactmatch/ru/common/v5/search"
WB_CARD_URL = "https://card.wb.ru/cards/detail"


class WBClient:
    """Клиент для работы с публичными эндпоинтами Wildberries.

    Предоставляет методы для поиска позиций товаров, получения информации
    о товарах и загрузки изображений. Включает кэширование и автоматические
    повторные попытки при сбоях сети.

    Attributes:
        _session: Асинхронная HTTP сессия aiohttp.
        _preview_cache: Кэш превью товаров (название, URL картинки, URL страницы).
        _image_cache: Кэш загруженных изображений.
        _image_negative_cache: Кэш неудачных попыток загрузки изображений.
        _cache_ttl_seconds: Время жизни кэша в секундах (по умолчанию 600).

    Example:
        >>> async with WBClient() as client:  # doctest: +SKIP
        ...     pos = await client.get_product_position(
        ...         sku=12345, query="кроссовки", device="pc", dest=-1257786
        ...     )
        ...     print(f"Позиция: {pos}")
    """

    def __init__(self) -> None:
        """Инициализирует клиент Wildberries с пустыми кэшами."""
        self._session: Optional[aiohttp.ClientSession] = None
        self._preview_cache: dict[int, tuple[Optional[str], str, str, float]] = {}
        self._image_cache: dict[int, tuple[bytes, float]] = {}
        self._image_negative_cache: dict[int, float] = {}
        self._cache_ttl_seconds: float = 600.0

    async def __aenter__(self) -> "WBClient":
        """Вход в контекстный менеджер."""
        await self._get_session()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        """Выход из контекстного менеджера с закрытием сессии."""
        await self.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        """Получает или создаёт HTTP сессию.

        Returns:
            Активная aiohttp сессия с настроенными таймаутами и коннектором.
        """
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=50,
                limit_per_host=20,
                ttl_dns_cache=300
            )
            # Таймаут побольше для API, но не для картинок
            timeout = aiohttp.ClientTimeout(total=8)
            # trust_env=True позволит использовать системные прокси (HTTPS_PROXY)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                trust_env=True
            )
        return self._session

    async def close(self) -> None:
        """Закрывает HTTP сессию и освобождает ресурсы."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _with_retries(
        self,
        coro_factory: Callable[[], asyncio.Future],
        *,
        attempts: int = 3,
        base_delay: float = 0.3
    ) -> Any:
        """Выполняет корутину с автоматическими повторными попытками.

        Args:
            coro_factory: Фабрика для создания корутины.
            attempts: Количество попыток (по умолчанию 3).
            base_delay: Базовая задержка между попытками в секундах.

        Returns:
            Результат выполнения корутины.

        Raises:
            Exception: Последнее исключение, если все попытки неудачны.
        """
        last_exc: Exception | None = None
        for i in range(attempts):
            try:
                return await coro_factory()
            except (asyncio.TimeoutError, ClientConnectorError) as exc:
                last_exc = exc
                delay = base_delay * (2 ** i)
                await asyncio.sleep(delay)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                break
        if last_exc:
            raise last_exc

    async def get_product_position(
        self,
        *,
        sku: int,
        query: str,
        device: str,
        dest: int
    ) -> Optional[int]:
        """Находит позицию товара в поисковой выдаче Wildberries.

        Параллельно запрашивает первые N страниц поиска и ищет товар с указанным SKU.

        Args:
            sku: Артикул товара (SKU).
            query: Поисковый запрос.
            device: Тип устройства (pc/android/ios).
            dest: Код региона Wildberries.

        Returns:
            Позиция товара (нумерация с 1) или None, если не найден.

        Example:
            >>> async with WBClient() as client:  # doctest: +SKIP
            ...     pos = await client.get_product_position(
            ...         sku=12345, query="кроссовки", device="pc", dest=-1257786
            ...     )
        """
        session = await self._get_session()
        per_page = 100
        max_pages = 2

        async def fetch_page(page: int) -> tuple[int, list[dict[str, Any]] | None]:
            """Запрашивает одну страницу результатов поиска."""
            params = {
                "query": query,
                "dest": dest,
                "resultset": "catalog",
                "page": page,
                "appType": _map_device_to_app_type(device),
            }
            start = time.perf_counter()
            try:
                async def do_request() -> Any:
                    return await session.get(
                        WB_SEARCH_URL,
                        params=params,
                        headers=_headers(device)
                    )
                
                async with await self._with_retries(do_request) as resp:
                    if resp.status != 200:
                        return page, None
                    data: dict[str, Any] = await resp.json(content_type=None)
                    products = data.get("data", {}).get("products")
                    return page, products if isinstance(products, list) else None
            except Exception:
                # Любой сбой превращаем в отсутствующие данные
                return page, None
            finally:
                elapsed = time.perf_counter() - start
                logger.debug(f"Поиск WB страница {page} '{query}' занял {elapsed:.2f}с")

        pages = list(range(1, max_pages + 1))
        results = await asyncio.gather(*(fetch_page(p) for p in pages))
        
        for page, products in sorted(results, key=lambda x: x[0]):
            if not products:
                continue
            for idx, item in enumerate(products, start=1):
                if int(item.get("id", 0)) == int(sku):
                    return (page - 1) * per_page + idx
        return None

    async def get_product_preview(
        self,
        *,
        sku: int,
        device: str,
        dest: int
    ) -> Tuple[Optional[str], str, str]:
        """Получает превью товара: название, URL картинки и URL страницы.

        Использует кэш для минимизации запросов к API.

        Args:
            sku: Артикул товара.
            device: Тип устройства.
            dest: Код региона.

        Returns:
            Кортеж (название, URL картинки, URL страницы товара).

        Example:
            >>> async with WBClient() as client:  # doctest: +SKIP
            ...     name, img_url, page_url = await client.get_product_preview(
            ...         sku=12345, device="pc", dest=-1257786
            ...     )
        """
        now = time.time()
        cached = self._preview_cache.get(sku)
        if cached and cached[3] > now:
            return cached[0], cached[1], cached[2]

        name: Optional[str] = None
        page_url = build_product_url(sku)
        image_url = build_image_url(sku)
        
        try:
            session = await self._get_session()
            params = {
                "appType": _map_device_to_app_type(device),
                "curr": "rub",
                "dest": dest,
                "nm": sku
            }
            start = time.perf_counter()
            
            async def do_request() -> Any:
                return await session.get(
                    WB_CARD_URL,
                    params=params,
                    headers=_headers(device)
                )
            
            async with await self._with_retries(do_request) as resp:
                if resp.status == 200:
                    data: dict[str, Any] = await resp.json(content_type=None)
                    products = data.get("data", {}).get("products") or []
                    if products:
                        name = products[0].get("name")
            
            logger.debug(
                f"Получение карточки WB для {sku} заняло {time.perf_counter()-start:.2f}с"
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Не удалось получить карточку WB для {sku}: {exc}")
        
        # Сохраняем в кэш
        exp = now + self._cache_ttl_seconds
        self._preview_cache[sku] = (name, image_url, page_url, exp)
        return name, image_url, page_url

    async def fetch_image_bytes(
        self,
        url: str,
        *,
        total_timeout: float = 3.0,
        attempts: int = 2
    ) -> Optional[bytes]:
        """Загружает изображение по URL.

        Args:
            url: URL изображения.
            total_timeout: Таймаут запроса в секундах.
            attempts: Количество попыток загрузки.

        Returns:
            Байты изображения или None при неудаче.
        """
        try:
            session = await self._get_session()
            headers = {
                "User-Agent": _headers("pc")["User-Agent"],
                "Referer": "https://www.wildberries.ru/"
            }
            # Короткий таймаут только для картинки
            timeout = aiohttp.ClientTimeout(total=total_timeout)
            
            async def do_request() -> Any:
                return await session.get(url, headers=headers, timeout=timeout)
            
            for i in range(attempts):
                try:
                    async with await do_request() as resp:
                        if resp.status == 200:
                            return await resp.read()
                except Exception as exc:  # noqa: BLE001
                    if i == attempts - 1:
                        logger.debug(f"Не удалось загрузить изображение WB: {exc}")
                        break
                    await asyncio.sleep(0.2 * (2 ** i))
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Не удалось загрузить изображение WB: {exc}")
        return None

    async def fetch_image_bytes_for_sku(self, sku: int) -> Optional[bytes]:
        """Загружает изображение товара по SKU с кэшированием.

        Пробует разные размеры изображений (big, tm, small). Использует
        кэш для избежания повторных загрузок.

        Args:
            sku: Артикул товара.

        Returns:
            Байты изображения или None.

        Example:
            >>> async with WBClient() as client:  # doctest: +SKIP
            ...     img = await client.fetch_image_bytes_for_sku(12345)
        """
        now = time.time()
        
        # Проверяем негативный кэш (чтобы не пытаться повторно)
        neg_exp = self._image_negative_cache.get(sku)
        if neg_exp and neg_exp > now:
            return None
        
        # Проверяем обычный кэш
        cached = self._image_cache.get(sku)
        if cached and cached[1] > now:
            return cached[0]
        
        # Пробуем загрузить разные размеры
        for size in ("big", "tm", "small"):
            url = build_image_url(sku, size=size)
            data = await self.fetch_image_bytes(url)
            if data:
                self._image_cache[sku] = (data, now + self._cache_ttl_seconds)
                return data
        
        # Сохраняем в негативный кэш на 5 минут
        self._image_negative_cache[sku] = now + 300
        return None


def _map_device_to_app_type(device: str) -> int:
    """Преобразует название устройства в appType для API Wildberries.

    Args:
        device: Тип устройства (pc/android/ios/и т.д.).

    Returns:
        Код appType для API (1, 32 или 64).

    Example:
        >>> _map_device_to_app_type("pc")
        1
        >>> _map_device_to_app_type("android")
        32
    """
    device = device.lower()
    if device in {"pc", "desktop", "web"}:
        return 1
    if device in {"android"}:
        return 32
    if device in {"ios", "iphone", "ipad", "tablet"}:
        return 64
    return 1


def _headers(device: str) -> dict[str, str]:
    """Возвращает HTTP заголовки с User-Agent для указанного устройства.

    Args:
        device: Тип устройства (pc/android/ios).

    Returns:
        Словарь с заголовками.

    Example:
        >>> headers = _headers("pc")
        >>> "User-Agent" in headers
        True
    """
    ua_map = {
        "pc": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "android": "Mozilla/5.0 (Linux; Android 12; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36",
        "ios": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1",
    }
    device = device.lower()
    ua = ua_map.get(device, ua_map["pc"])
    return {"User-Agent": ua}


def build_image_url(nm_id: int, size: str = "big") -> str:
    """Строит URL изображения товара Wildberries.

    Args:
        nm_id: Артикул товара.
        size: Размер изображения (big/tm/small).

    Returns:
        URL изображения.

    Example:
        >>> build_image_url(12345678, "big")  # doctest: +SKIP
        'https://images.wbstatic.net/big/new/123/12345/12345678-1.jpg'
    """
    vol = nm_id // 100000
    part = nm_id // 1000
    return f"https://images.wbstatic.net/{size}/new/{vol}/{part}/{nm_id}-1.jpg"


def build_product_url(nm_id: int) -> str:
    """Строит URL страницы товара на сайте Wildberries.

    Args:
        nm_id: Артикул товара.

    Returns:
        URL страницы товара.

    Example:
        >>> build_product_url(12345678)
        'https://www.wildberries.ru/catalog/12345678/detail.aspx'
    """
    return f"https://www.wildberries.ru/catalog/{nm_id}/detail.aspx"
