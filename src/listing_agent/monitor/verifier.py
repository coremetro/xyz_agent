from __future__ import annotations

from typing import Any

from ..timeutil import now_ms
from .client import AsyncHyperliquidInfoClient
from .models import STATE_CHANGED, AssetEvent, AssetSnapshot, MonitorAsset, VerificationResult
from .scoring import score_asset
from .state_machine import infer_state
from .storage import JsonMonitorStore


class AssetVerifier:
    def __init__(self, client: AsyncHyperliquidInfoClient, store: JsonMonitorStore, dex: str = "xyz") -> None:
        self.client = client
        self.store = store
        self.dex = dex

    async def verify(self, ticker: str, metadata: dict[str, Any] | None = None) -> VerificationResult:
        event_time_ms = now_ms()
        metadata = metadata or {}
        mids = await _safe(self.client.all_mids(self.dex), {})
        ctx_payload = await _safe(self.client.meta_and_asset_ctxs(self.dex), None)
        book = await _safe(self.client.l2_book(ticker), None)
        trades = await _safe(self.client.recent_trades(ticker), [])
        ctx = _find_context(ctx_payload, ticker)
        metadata = metadata or _find_metadata(ctx_payload, ticker)
        mid_px = _mid_for_ticker(mids, ticker)
        best_bid, best_ask, depth_usd = _book_metrics(book)
        mark_px = _float_from_keys(ctx, ("markPx", "mark_px", "mark"))
        oracle_px = _float_from_keys(ctx, ("oraclePx", "oracle_px", "oracle"))
        if mid_px is None:
            mid_px = _float_from_keys(ctx, ("midPx", "mid_px", "mid"))
        open_interest = _float_from_keys(ctx, ("openInterest", "open_interest", "oi"))
        funding = _float_from_keys(ctx, ("funding", "fundingRate"))
        spread_bps = _spread_bps(best_bid, best_ask)
        trade_count = len(trades) if isinstance(trades, list) else 0
        snapshot = AssetSnapshot(
            dex=self.dex,
            ticker=ticker,
            snapshot_time_ms=event_time_ms,
            mark_px=mark_px,
            oracle_px=oracle_px,
            mid_px=mid_px,
            open_interest=open_interest,
            funding=funding,
            best_bid=best_bid,
            best_ask=best_ask,
            spread_bps=spread_bps,
            book_depth_usd=depth_usd,
            payload={"ctx": ctx, "book": book, "trade_count": trade_count},
        )
        state = infer_state(snapshot, trade_count=trade_count)
        score, action, reasons = score_asset(snapshot, metadata, trade_count=trade_count)
        result = VerificationResult(self.dex, ticker, state, score, action, snapshot, metadata, reasons)
        self.store.write_snapshot(snapshot)
        self._update_state(result, event_time_ms)
        return result

    def _update_state(self, result: VerificationResult, event_time_ms: int) -> None:
        assets = self.store.load_assets()
        key = f"{self.dex.lower()}:{result.ticker.upper()}"
        current = assets.get(key)
        old_state = current.current_state if current is not None else None
        if current is None:
            self.store.upsert_asset(
                MonitorAsset(self.dex, result.ticker, event_time_ms, "verifier", result.state, event_time_ms, result.metadata)
            )
            return
        if old_state != result.state:
            self.store.upsert_asset(
                MonitorAsset(
                    current.dex,
                    current.ticker,
                    current.first_seen_at_ms,
                    current.first_seen_source,
                    result.state,
                    event_time_ms,
                    result.metadata or current.metadata,
                )
            )
            self.store.write_event(
                AssetEvent(
                    self.dex,
                    result.ticker,
                    STATE_CHANGED,
                    "asset_verifier",
                    event_time_ms,
                    {"old_state": old_state, "new_state": result.state, "score": result.score},
                )
            )


async def _safe(awaitable: Any, default: Any) -> Any:
    try:
        return await awaitable
    except Exception:
        return default


def _find_metadata(payload: Any, ticker: str) -> dict[str, Any]:
    meta = payload[0] if isinstance(payload, list) and payload else None
    universe = meta.get("universe") if isinstance(meta, dict) else None
    if not isinstance(universe, list):
        return {}
    for item in universe:
        if isinstance(item, dict) and str(item.get("name", "")).upper() == ticker.upper():
            return item
    return {}


def _find_context(payload: Any, ticker: str) -> dict[str, Any]:
    if not isinstance(payload, list) or len(payload) < 2:
        return {}
    meta = payload[0] if isinstance(payload[0], dict) else {}
    ctxs = payload[1] if isinstance(payload[1], list) else []
    universe = meta.get("universe") if isinstance(meta, dict) else []
    if not isinstance(universe, list):
        return {}
    for index, item in enumerate(universe):
        if isinstance(item, dict) and str(item.get("name", "")).upper() == ticker.upper():
            ctx = ctxs[index] if index < len(ctxs) and isinstance(ctxs[index], dict) else {}
            return ctx
    return {}


def _mid_for_ticker(payload: Any, ticker: str) -> float | None:
    mids = payload.get("mids", payload) if isinstance(payload, dict) else {}
    if not isinstance(mids, dict):
        return None
    for key in (ticker, ticker.upper(), ticker.split(":")[-1], ticker.upper().split(":")[-1]):
        if key in mids:
            return _float(mids[key])
    return None


def _book_metrics(payload: Any) -> tuple[float | None, float | None, float | None]:
    levels = payload.get("levels") if isinstance(payload, dict) else None
    if not isinstance(levels, list) or len(levels) < 2:
        return None, None, None
    bids = levels[0] if isinstance(levels[0], list) else []
    asks = levels[1] if isinstance(levels[1], list) else []
    best_bid = _float(bids[0].get("px")) if bids and isinstance(bids[0], dict) else None
    best_ask = _float(asks[0].get("px")) if asks and isinstance(asks[0], dict) else None
    depth = 0.0
    for side in (bids, asks):
        for level in side[:5]:
            if not isinstance(level, dict):
                continue
            px = _float(level.get("px"))
            sz = _float(level.get("sz"))
            if px is not None and sz is not None:
                depth += px * sz
    return best_bid, best_ask, round(depth, 2) if depth else None


def _spread_bps(best_bid: float | None, best_ask: float | None) -> float | None:
    if best_bid is None or best_ask is None or best_bid <= 0 or best_ask <= 0:
        return None
    mid = (best_bid + best_ask) / 2
    return round((best_ask - best_bid) / mid * 10_000, 2)


def _float_from_keys(payload: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key in payload:
            return _float(payload[key])
    return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
