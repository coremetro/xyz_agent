from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

from ..timeutil import now_ms
from .models import VerificationResult
from .storage import JsonMonitorStore


class WebhookAlertService:
    def __init__(self, store: JsonMonitorStore, webhook_url: str = "", timeout_s: float = 5.0) -> None:
        self.store = store
        self.webhook_url = webhook_url
        self.timeout_s = timeout_s

    def send_if_needed(self, result: VerificationResult) -> bool:
        if self.store.alert_was_sent(result.dex, result.ticker, result.state):
            return False
        payload = self.format_alert(result)
        if self.webhook_url:
            self._post(payload)
        self.store.mark_alert_sent(result.dex, result.ticker, result.state, now_ms(), payload)
        return True

    def format_alert(self, result: VerificationResult) -> dict[str, Any]:
        snapshot = result.snapshot
        text = (
            "[trade.xyz new asset candidate]\n"
            f"Ticker: {result.ticker}\n"
            f"DEX: {result.dex}\n"
            f"State: {result.state}\n"
            f"Score: {result.score}/100\n"
            f"Action: {result.recommended_action}\n"
            f"mid={snapshot.mid_px} mark={snapshot.mark_px} oracle={snapshot.oracle_px}\n"
            f"bid={snapshot.best_bid} ask={snapshot.best_ask} spread_bps={snapshot.spread_bps}\n"
            f"book_depth_usd={snapshot.book_depth_usd} oi={snapshot.open_interest} funding={snapshot.funding}"
        )
        return {"content": text, "result": result.to_dict()}

    def _post(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        request = Request(self.webhook_url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=self.timeout_s) as response:
            response.read()

