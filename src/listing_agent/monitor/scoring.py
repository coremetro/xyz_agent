from __future__ import annotations

from typing import Any

from .models import AssetSnapshot


def score_asset(snapshot: AssetSnapshot, metadata: dict[str, Any], trade_count: int = 0) -> tuple[int, str, list[str]]:
    score = 20
    reasons = ["metadata detected +20"]
    if snapshot.oracle_px is not None or snapshot.mark_px is not None:
        score += 15
        reasons.append("oracle or mark price detected +15")
    if snapshot.mid_px is not None:
        score += 15
        reasons.append("mid price detected +15")
    if snapshot.best_bid is not None and snapshot.best_ask is not None:
        score += 15
        reasons.append("order book detected +15")
    else:
        score -= 20
        reasons.append("order book empty -20")
    if trade_count > 0:
        score += 15
        reasons.append("recent trades detected +15")

    if snapshot.open_interest is not None and snapshot.open_interest > 0:
        score += 10
        reasons.append("open interest positive +10")
    if snapshot.spread_bps is not None and snapshot.spread_bps > 200:
        score -= 15
        reasons.append("spread above 200 bps -15")
    if snapshot.book_depth_usd is not None and snapshot.book_depth_usd < 1_000:
        score -= 15
        reasons.append("book depth below 1000 USD -15")
    if _premium_abs_bps(snapshot) is not None and _premium_abs_bps(snapshot) > 500:
        score -= 10
        reasons.append("mark/oracle premium above 500 bps -10")
    if metadata.get("isDelisted") is True or metadata.get("delisted") is True:
        score -= 50
        reasons.append("asset is delisted -50")
    if metadata.get("haltTrading") is True:
        score -= 50
        reasons.append("trading halted -50")

    bounded = max(0, min(100, score))
    return bounded, recommended_action(bounded), reasons


def recommended_action(score: int) -> str:
    if score >= 80:
        return "HIGH_PRIORITY_WATCH"
    if score >= 60:
        return "MANUAL_REVIEW"
    if score >= 40:
        return "PASSIVE_WATCH"
    return "IGNORE_OR_LOG_ONLY"


def _premium_abs_bps(snapshot: AssetSnapshot) -> float | None:
    if snapshot.mark_px is None or snapshot.oracle_px in (None, 0):
        return None
    return abs((snapshot.mark_px / snapshot.oracle_px - 1) * 10_000)

