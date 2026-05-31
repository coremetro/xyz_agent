from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from ..timeutil import now_ms
from .models import MID_DETECTED, NEW_MID_KEY, AssetEvent, MonitorAsset
from .storage import JsonMonitorStore


class AllMidsWatcher:
    def __init__(
        self,
        ws_url: str,
        store: JsonMonitorStore,
        dex: str = "xyz",
        reconnect_delay_s: float = 2.0,
        on_event: Callable[[AssetEvent], Awaitable[None]] | None = None,
    ) -> None:
        self.ws_url = ws_url
        self.store = store
        self.dex = dex
        self.reconnect_delay_s = reconnect_delay_s
        self.on_event = on_event

    async def run(self) -> None:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("Install websockets to run AllMidsWatcher") from exc

        while True:
            try:
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=20) as ws:
                    await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "allMids", "dex": self.dex}}))
                    async for message in ws:
                        for event in self.handle_message(message):
                            self.store.write_event(event)
                            if self.on_event is not None:
                                await self.on_event(event)
            except Exception:
                await asyncio.sleep(self.reconnect_delay_s)

    def handle_message(self, message: str | bytes) -> list[AssetEvent]:
        data = json.loads(message)
        mids = extract_mids(data)
        known = self.store.known_tickers(self.dex)
        events: list[AssetEvent] = []
        event_time_ms = now_ms()
        for ticker in sorted(mids):
            if ticker in known:
                continue
            event = AssetEvent(self.dex, ticker, NEW_MID_KEY, "hyperliquid_ws_allMids", event_time_ms, {"mid": mids[ticker]})
            self.store.upsert_asset(MonitorAsset(self.dex, ticker, event_time_ms, "hyperliquid_ws_allMids", MID_DETECTED, event_time_ms, {}))
            events.append(event)
        return events


def extract_mids(data: Any) -> dict[str, str]:
    payload = data.get("data", data) if isinstance(data, dict) else {}
    mids = payload.get("mids", payload) if isinstance(payload, dict) else {}
    if not isinstance(mids, dict):
        return {}
    return {str(key).upper(): str(value) for key, value in mids.items()}
