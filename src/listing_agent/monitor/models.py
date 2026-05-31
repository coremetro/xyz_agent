from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


UNKNOWN = "UNKNOWN"
METADATA_DETECTED = "METADATA_DETECTED"
ORACLE_DETECTED = "ORACLE_DETECTED"
MID_DETECTED = "MID_DETECTED"
BOOK_DETECTED = "BOOK_DETECTED"
TRADE_DETECTED = "TRADE_DETECTED"
PUBLIC_ANNOUNCED = "PUBLIC_ANNOUNCED"

NEW_METADATA_ASSET = "NEW_METADATA_ASSET"
NEW_MID_KEY = "NEW_MID_KEY"
ORACLE_PRICE_DETECTED = "ORACLE_PRICE_DETECTED"
BOOK_EVENT_DETECTED = "BOOK_DETECTED"
TRADE_EVENT_DETECTED = "TRADE_DETECTED"
STATE_CHANGED = "STATE_CHANGED"
ALERT_SENT = "ALERT_SENT"


@dataclass(frozen=True)
class MonitorAsset:
    dex: str
    ticker: str
    first_seen_at_ms: int
    first_seen_source: str
    current_state: str
    last_state_change_at_ms: int | None
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AssetEvent:
    dex: str
    ticker: str
    event_type: str
    event_source: str
    event_time_ms: int
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AssetSnapshot:
    dex: str
    ticker: str
    snapshot_time_ms: int
    mark_px: float | None = None
    oracle_px: float | None = None
    mid_px: float | None = None
    open_interest: float | None = None
    funding: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    spread_bps: float | None = None
    book_depth_usd: float | None = None
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationResult:
    dex: str
    ticker: str
    state: str
    score: int
    recommended_action: str
    snapshot: AssetSnapshot
    metadata: dict[str, Any]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["snapshot"] = self.snapshot.to_dict()
        return payload

