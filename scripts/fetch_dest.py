from __future__ import annotations

import asyncio
import sys
from typing import Any

import aiohttp

URL = "https://user-geo-data.wildberries.ru/get-geo-info"


async def fetch_dest(latitude: float, longitude: float, address: str) -> int | None:
	params = {"latitude": latitude, "longitude": longitude, "address": address}
	async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
		async with session.get(URL, params=params) as resp:
			resp.raise_for_status()
			data: dict[str, Any] = await resp.json(content_type=None)
			xinfo = data.get("xinfo", "")
			for part in str(xinfo).split("&"):
				if part.startswith("dest="):
					return int(part.split("=", 1)[1])
	return None


async def main() -> None:
	if len(sys.argv) < 4:
		print("Usage: python scripts/fetch_dest.py <lat> <lon> <address>")
		return
	lat = float(sys.argv[1])
	lon = float(sys.argv[2])
	addr = " ".join(sys.argv[3:])
	dest = await fetch_dest(lat, lon, addr)
	print(dest)


if __name__ == "__main__":
	asyncio.run(main())
