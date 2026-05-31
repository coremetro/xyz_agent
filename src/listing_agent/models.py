from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Asset:
    market_type: str
    asset_id: str
    symbol: str
    raw: dict[str, Any]

    @property
    def key(self) -> str:
        return f"{self.market_type}:{self.asset_id}"

    @property
    def normalized_symbol(self) -> str:
        return self.symbol.upper()


@dataclass(frozen=True)
class Snapshot:
    assets: dict[str, Asset]
    fetched_at_ms: int
    latency_ms: float
    raw_hash: str


@dataclass(frozen=True)
class Candidate:
    asset: Asset
    discovered_at_ms: int
    reason: str


@dataclass(frozen=True)
class MarketCheck:
    approved: bool
    reason: str
    context: dict[str, Any] | None = None


@dataclass(frozen=True)
class OrderIntent:
    idempotency_key: str
    asset_key: str
    symbol: str
    side: str
    notional_usd: float
    order_type: str
    dry_run: bool
    reason: str
