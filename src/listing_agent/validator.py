from __future__ import annotations

from typing import Any

from .config import AgentConfig
from .hyperliquid_client import HyperliquidInfoClient
from .models import Asset, Candidate, MarketCheck


class MarketValidator:
    def __init__(self, client: HyperliquidInfoClient, config: AgentConfig) -> None:
        self.client = client
        self.config = config

    def validate(self, candidate: Candidate) -> MarketCheck:
        asset = candidate.asset
        symbol = asset.normalized_symbol
        if self.config.allowlist and symbol not in self.config.allowlist:
            return MarketCheck(False, "asset is not in allowlist")
        if symbol in self.config.denylist:
            return MarketCheck(False, "asset is in denylist")

        try:
            context = self._find_context(asset)
        except Exception as exc:
            return MarketCheck(False, f"context fetch failed: {exc}")
        if context is None:
            return MarketCheck(False, "asset missing from fresh context response")

        if _is_delisted_or_invalid(context):
            return MarketCheck(False, "context indicates non-tradable or invalid market", context)
        return MarketCheck(True, "candidate passed metadata/context checks", context)

    def _find_context(self, asset: Asset) -> dict[str, Any] | None:
        if asset.market_type == "perp":
            response, _ = self.client.perp_meta_and_contexts()
            if not isinstance(response, list) or len(response) < 2:
                raise ValueError("unexpected perp context response")
            meta, contexts = response[0], response[1]
            if not isinstance(meta, dict) or not isinstance(contexts, list):
                raise ValueError("unexpected perp context shape")
            key_order = _asset_list_for_market("perp", meta)
            return _context_by_asset(key_order, contexts, asset)

        response, _ = self.client.spot_meta_and_contexts()
        if not isinstance(response, list) or len(response) < 2:
            raise ValueError("unexpected spot context response")
        meta, contexts = response[0], response[1]
        if not isinstance(meta, dict) or not isinstance(contexts, list):
            raise ValueError("unexpected spot context shape")
        key_order = _asset_list_for_market("spot", meta)
        return _context_by_asset(key_order, contexts, asset)


def _asset_list_for_market(market_type: str, meta: dict[str, Any]) -> list[Asset]:
    from .metadata import parse_perp_asset_list, parse_spot_asset_list

    if market_type == "perp":
        return parse_perp_asset_list(meta)
    return parse_spot_asset_list(meta)


def _context_by_asset(ordered_assets: list[Asset], contexts: list[Any], asset: Asset) -> dict[str, Any] | None:
    for index, ordered in enumerate(ordered_assets):
        if ordered.key == asset.key and index < len(contexts):
            context = contexts[index]
            return context if isinstance(context, dict) else None
    return None


def _is_delisted_or_invalid(context: dict[str, Any]) -> bool:
    for key in ("isDelisted", "delisted", "onlyIsolated"):
        if context.get(key) is True and key != "onlyIsolated":
            return True
    mark_px = context.get("markPx") or context.get("midPx") or context.get("oraclePx")
    try:
        return mark_px is not None and float(mark_px) <= 0
    except (TypeError, ValueError):
        return True
