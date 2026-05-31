from __future__ import annotations

from typing import Any

from ..timeutil import now_ms
from .client import AsyncHyperliquidInfoClient
from .models import METADATA_DETECTED, NEW_METADATA_ASSET, AssetEvent, MonitorAsset
from .storage import JsonMonitorStore


class MetadataWatcher:
    def __init__(self, client: AsyncHyperliquidInfoClient, store: JsonMonitorStore, dex: str = "xyz") -> None:
        self.client = client
        self.store = store
        self.dex = dex

    async def fetch_assets(self) -> dict[str, dict[str, Any]]:
        metas = await self.client.all_perp_metas()
        dexs = await self.client.perp_dexs()
        return extract_dex_assets(metas, dexs, self.dex)

    async def run_once(self, init_baseline: bool = False) -> list[AssetEvent]:
        fetched_at_ms = now_ms()
        current_assets = await self.fetch_assets()
        known = self.store.known_tickers(self.dex)
        if init_baseline or not known:
            for ticker, metadata in sorted(current_assets.items()):
                self.store.upsert_asset(
                    MonitorAsset(self.dex, ticker, fetched_at_ms, "hyperliquid_metadata_baseline", METADATA_DETECTED, fetched_at_ms, metadata)
                )
            return []

        events: list[AssetEvent] = []
        for ticker, metadata in sorted(current_assets.items()):
            if ticker in known:
                continue
            asset = MonitorAsset(self.dex, ticker, fetched_at_ms, "hyperliquid_metadata", METADATA_DETECTED, fetched_at_ms, metadata)
            event = AssetEvent(self.dex, ticker, NEW_METADATA_ASSET, "hyperliquid_allPerpMetas", fetched_at_ms, metadata)
            self.store.upsert_asset(asset)
            self.store.write_event(event)
            events.append(event)
        return events


def extract_dex_assets(metas: Any, dexs: Any, dex: str) -> dict[str, dict[str, Any]]:
    if not isinstance(metas, list) or not isinstance(dexs, list):
        raise ValueError("Expected allPerpMetas and perpDexs list responses")
    for index, meta in enumerate(metas):
        dex_meta = dexs[index] if index < len(dexs) else None
        dex_name = "core" if dex_meta is None else str(dex_meta.get("name", ""))
        if dex_name.lower() != dex.lower():
            continue
        universe = meta.get("universe") if isinstance(meta, dict) else None
        if not isinstance(universe, list):
            return {}
        output: dict[str, dict[str, Any]] = {}
        for item in universe:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            ticker = str(item["name"]).upper()
            output[ticker] = item
        return output
    return {}

