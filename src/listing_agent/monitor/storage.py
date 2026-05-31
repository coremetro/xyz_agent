from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import ALERT_SENT, AssetEvent, AssetSnapshot, MonitorAsset


class JsonMonitorStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.assets_path = root / "assets.json"
        self.events_path = root / "asset_events.jsonl"
        self.snapshots_path = root / "asset_snapshots.jsonl"
        self.alerts_path = root / "alerts.jsonl"

    def load_assets(self) -> dict[str, MonitorAsset]:
        if not self.assets_path.exists():
            return {}
        data = json.loads(self.assets_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("assets.json must contain an object")
        return {
            key: MonitorAsset(
                dex=str(item["dex"]),
                ticker=str(item["ticker"]),
                first_seen_at_ms=int(item["first_seen_at_ms"]),
                first_seen_source=str(item["first_seen_source"]),
                current_state=str(item["current_state"]),
                last_state_change_at_ms=item.get("last_state_change_at_ms"),
                metadata=item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {},
            )
            for key, item in data.items()
            if isinstance(item, dict)
        }

    def known_tickers(self, dex: str) -> set[str]:
        return {
            asset.ticker
            for asset in self.load_assets().values()
            if asset.dex.lower() == dex.lower()
        }

    def upsert_asset(self, asset: MonitorAsset) -> None:
        assets = self.load_assets()
        assets[_asset_key(asset.dex, asset.ticker)] = asset
        self._write_json(self.assets_path, {key: value.to_dict() for key, value in sorted(assets.items())})

    def write_event(self, event: AssetEvent) -> None:
        self._append_jsonl(self.events_path, event.to_dict())

    def write_snapshot(self, snapshot: AssetSnapshot) -> None:
        self._append_jsonl(self.snapshots_path, snapshot.to_dict())

    def alert_was_sent(self, dex: str, ticker: str, state: str) -> bool:
        if not self.alerts_path.exists():
            return False
        key = {"dex": dex, "ticker": ticker, "state": state}
        with self.alerts_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if all(item.get(name) == value for name, value in key.items()):
                    return True
        return False

    def mark_alert_sent(self, dex: str, ticker: str, state: str, event_time_ms: int, payload: dict[str, Any]) -> None:
        record = {"dex": dex, "ticker": ticker, "state": state, "event_time_ms": event_time_ms, "payload": payload}
        self._append_jsonl(self.alerts_path, record)
        self.write_event(AssetEvent(dex, ticker, ALERT_SENT, "alert_service", event_time_ms, payload))

    def _write_json(self, path: Path, payload: Any) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _append_jsonl(self, path: Path, payload: Any) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            json.dump(_jsonable(payload), handle, sort_keys=True)
            handle.write("\n")


def _asset_key(dex: str, ticker: str) -> str:
    return f"{dex.lower()}:{ticker.upper()}"


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return value

