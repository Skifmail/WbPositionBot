from __future__ import annotations

import asyncio
import time
from typing import Any, Optional, Tuple, Callable

import aiohttp
from aiohttp import ClientConnectorError
from loguru import logger

WB_SEARCH_URL = "https://search.wb.ru/exactmatch/ru/common/v5/search"
WB_CARD_URL = "https://card.wb.ru/cards/detail"


class WBClient:
	"""Wildberries public endpoints client."""

	def __init__(self) -> None:
		self._session: Optional[aiohttp.ClientSession] = None
		self._preview_cache: dict[int, tuple[Optional[str], str, str, float]] = {}
		self._image_cache: dict[int, tuple[bytes, float]] = {}
		self._image_negative_cache: dict[int, float] = {}
		self._cache_ttl_seconds: float = 600.0

	async def __aenter__(self) -> "WBClient":
		await self._get_session()
		return self

	async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001, ANN201
		await self.close()

	async def _get_session(self) -> aiohttp.ClientSession:
		if self._session is None or self._session.closed:
			connector = aiohttp.TCPConnector(limit=50, limit_per_host=20, ttl_dns_cache=300)
			# total timeout побольше для API, но не для картинок
			timeout = aiohttp.ClientTimeout(total=8)
			# trust_env=True позволит использовать системные/ENV прокси (HTTPS_PROXY)
			self._session = aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=True)
		return self._session

	async def close(self) -> None:
		if self._session and not self._session.closed:
			await self._session.close()

	async def _with_retries(self, coro_factory: Callable[[], asyncio.Future], *, attempts: int = 3, base_delay: float = 0.3) -> Any:
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

	async def get_product_position(self, *, sku: int, query: str, device: str, dest: int) -> Optional[int]:
		"""Return 1-based position of sku for given query and dest. None if not found on first N pages."""
		session = await self._get_session()
		per_page = 100
		max_pages = 2

		async def fetch_page(page: int) -> tuple[int, list[dict[str, Any]] | None]:
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
					return await session.get(WB_SEARCH_URL, params=params, headers=_headers(device))
				async with await self._with_retries(do_request) as resp:
					if resp.status != 200:
						return page, None
					data: dict[str, Any] = await resp.json(content_type=None)
					products = data.get("data", {}).get("products")
					return page, products if isinstance(products, list) else None
			except Exception:  # любой сбой превращаем в отсутствующие данные
				return page, None
			finally:
				elapsed = time.perf_counter() - start
				logger.debug(f"WB search page {page} '{query}' took {elapsed:.2f}s")

		pages = list(range(1, max_pages + 1))
		results = await asyncio.gather(*(fetch_page(p) for p in pages))
		for page, products in sorted(results, key=lambda x: x[0]):
			if not products:
				continue
			for idx, item in enumerate(products, start=1):
				if int(item.get("id", 0)) == int(sku):
					return (page - 1) * per_page + idx
		return None

	async def get_product_preview(self, *, sku: int, device: str, dest: int) -> Tuple[Optional[str], str, str]:
		"""Fetch product name and preview image URL along with product page URL with caching."""
		now = time.time()
		cached = self._preview_cache.get(sku)
		if cached and cached[3] > now:
			return cached[0], cached[1], cached[2]

		name: Optional[str] = None
		page_url = build_product_url(sku)
		image_url = build_image_url(sku)
		try:
			session = await self._get_session()
			params = {"appType": _map_device_to_app_type(device), "curr": "rub", "dest": dest, "nm": sku}
			start = time.perf_counter()
			async def do_request() -> Any:
				return await session.get(WB_CARD_URL, params=params, headers=_headers(device))
			async with await self._with_retries(do_request) as resp:
				if resp.status == 200:
					data: dict[str, Any] = await resp.json(content_type=None)
					products = data.get("data", {}).get("products") or []
					if products:
						name = products[0].get("name")
			logger.debug(f"WB card for {sku} took {time.perf_counter()-start:.2f}s")
		except Exception as exc:  # noqa: BLE001
			logger.debug(f"WB card fetch failed for {sku}: {exc}")
		# cache
		exp = now + self._cache_ttl_seconds
		self._preview_cache[sku] = (name, image_url, page_url, exp)
		return name, image_url, page_url

	async def fetch_image_bytes(self, url: str, *, total_timeout: float = 3.0, attempts: int = 2) -> Optional[bytes]:
		try:
			session = await self._get_session()
			headers = {"User-Agent": _headers("pc")["User-Agent"], "Referer": "https://www.wildberries.ru/"}
			# короткий таймаут только для картинки
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
						logger.debug(f"WB image fetch failed: {exc}")
						break
					await asyncio.sleep(0.2 * (2 ** i))
		except Exception as exc:  # noqa: BLE001
			logger.debug(f"WB image fetch failed: {exc}")
		return None

	async def fetch_image_bytes_for_sku(self, sku: int) -> Optional[bytes]:
		now = time.time()
		# негативный кэш, чтобы не пытаться регулярно в TTL
		neg_exp = self._image_negative_cache.get(sku)
		if neg_exp and neg_exp > now:
			return None
		cached = self._image_cache.get(sku)
		if cached and cached[1] > now:
			return cached[0]
		for size in ("big", "tm", "small"):
			url = build_image_url(sku, size=size)
			data = await self.fetch_image_bytes(url)
			if data:
				self._image_cache[sku] = (data, now + self._cache_ttl_seconds)
				return data
		# негативный кэш на 5 минут
		self._image_negative_cache[sku] = now + 300
		return None


def _map_device_to_app_type(device: str) -> int:
	device = device.lower()
	if device in {"pc", "desktop", "web"}:
		return 1
	if device in {"android"}:
		return 32
	if device in {"ios", "iphone", "ipad", "tablet"}:
		return 64
	return 1


def _headers(device: str) -> dict[str, str]:
	ua_map = {
		"pc": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
		"android": "Mozilla/5.0 (Linux; Android 12; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36",
		"ios": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1",
	}
	device = device.lower()
	ua = ua_map.get(device, ua_map["pc"])
	return {"User-Agent": ua}


def build_image_url(nm_id: int, size: str = "big") -> str:
	vol = nm_id // 100000
	part = nm_id // 1000
	return f"https://images.wbstatic.net/{size}/new/{vol}/{part}/{nm_id}-1.jpg"


def build_product_url(nm_id: int) -> str:
	return f"https://www.wildberries.ru/catalog/{nm_id}/detail.aspx"
