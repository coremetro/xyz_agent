from __future__ import annotations

from .models import (
    BOOK_DETECTED,
    METADATA_DETECTED,
    MID_DETECTED,
    ORACLE_DETECTED,
    TRADE_DETECTED,
    AssetSnapshot,
)


def infer_state(snapshot: AssetSnapshot, trade_count: int = 0) -> str:
    if trade_count > 0:
        return TRADE_DETECTED
    if snapshot.best_bid is not None and snapshot.best_ask is not None:
        return BOOK_DETECTED
    if snapshot.mid_px is not None:
        return MID_DETECTED
    if snapshot.oracle_px is not None or snapshot.mark_px is not None:
        return ORACLE_DETECTED
    return METADATA_DETECTED

