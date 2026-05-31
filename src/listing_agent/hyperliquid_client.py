from __future__ import annotations

import json
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .timeutil import monotonic_ms


class HyperliquidInfoClient:
    def __init__(self, api_url: str, timeout_s: float = 5.0) -> None:
        self.api_url = api_url
        self.timeout_s = timeout_s
        self.ssl_context = _ssl_context()

    def post(self, payload: dict[str, Any]) -> tuple[Any, float]:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(
            self.api_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = monotonic_ms()
        try:
            with urlopen(request, timeout=self.timeout_s, context=self.ssl_context) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Hyperliquid HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Hyperliquid network error: {exc.reason}") from exc
        latency_ms = monotonic_ms() - started
        return json.loads(raw), latency_ms

    def perp_meta(self) -> tuple[Any, float]:
        return self.post({"type": "meta"})

    def perp_meta_and_contexts(self) -> tuple[Any, float]:
        return self.post({"type": "metaAndAssetCtxs"})

    def spot_meta(self) -> tuple[Any, float]:
        return self.post({"type": "spotMeta"})

    def spot_meta_and_contexts(self) -> tuple[Any, float]:
        return self.post({"type": "spotMetaAndAssetCtxs"})

    def candles(
        self,
        coin: str,
        interval: str,
        start_time_ms: int,
        end_time_ms: int,
    ) -> tuple[Any, float]:
        return self.post(
            {
                "type": "candleSnapshot",
                "req": {
                    "coin": coin,
                    "interval": interval,
                    "startTime": start_time_ms,
                    "endTime": end_time_ms,
                },
            }
        )


def _ssl_context() -> ssl.SSLContext | None:
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())
