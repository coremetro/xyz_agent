from __future__ import annotations

import asyncio
from typing import Any

from ..hyperliquid_client import HyperliquidInfoClient


class AsyncHyperliquidInfoClient:
    def __init__(self, api_url: str = "https://api.hyperliquid.xyz/info", timeout_s: float = 5.0, retries: int = 2) -> None:
        self._client = HyperliquidInfoClient(api_url, timeout_s=timeout_s)
        self.retries = retries

    async def post_info(self, payload: dict[str, Any]) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response, _ = await asyncio.to_thread(self._client.post, payload)
                return response
            except Exception as exc:  # noqa: BLE001 - converted into final retry failure.
                last_exc = exc
                if attempt < self.retries:
                    await asyncio.sleep(0.25 * (attempt + 1))
        assert last_exc is not None
        raise last_exc

    async def all_perp_metas(self) -> Any:
        return await self.post_info({"type": "allPerpMetas"})

    async def perp_dexs(self) -> Any:
        return await self.post_info({"type": "perpDexs"})

    async def meta_and_asset_ctxs(self, dex: str = "xyz") -> Any:
        return await self.post_info({"type": "metaAndAssetCtxs", "dex": dex})

    async def all_mids(self, dex: str = "xyz") -> Any:
        return await self.post_info({"type": "allMids", "dex": dex})

    async def l2_book(self, coin: str) -> Any:
        return await self.post_info({"type": "l2Book", "coin": coin})

    async def recent_trades(self, coin: str) -> Any:
        return await self.post_info({"type": "recentTrades", "coin": coin})

