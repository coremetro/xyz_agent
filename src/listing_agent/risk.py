from __future__ import annotations

from .config import AgentConfig
from .models import Candidate, MarketCheck, OrderIntent


class RiskEngine:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self._seen_order_keys: set[str] = set()

    def create_buy_intent(
        self,
        candidate: Candidate,
        market_check: MarketCheck,
        notional_usd: float | None = None,
    ) -> OrderIntent:
        if not market_check.approved:
            raise ValueError(f"Cannot create order intent for rejected candidate: {market_check.reason}")
        requested_notional = self.config.max_notional_usd if notional_usd is None else notional_usd
        if requested_notional <= 0:
            raise ValueError("MAX_NOTIONAL_USD must be positive")
        if requested_notional > self.config.max_notional_usd:
            raise ValueError("Requested notional exceeds MAX_NOTIONAL_USD")
        if requested_notional > self.config.max_total_exposure_usd:
            raise ValueError("Requested notional exceeds MAX_TOTAL_EXPOSURE_USD")

        key = f"buy:{candidate.asset.key}:{candidate.discovered_at_ms}"
        if key in self._seen_order_keys:
            raise ValueError("duplicate order intent suppressed")
        self._seen_order_keys.add(key)

        return OrderIntent(
            idempotency_key=key,
            asset_key=candidate.asset.key,
            symbol=candidate.asset.symbol,
            side="buy",
            notional_usd=requested_notional,
            order_type=f"marketable_limit_with_{self.config.slippage_bps:g}bps_slippage_cap",
            dry_run=self.config.dry_run,
            reason="new listing candidate passed risk pre-checks",
        )
