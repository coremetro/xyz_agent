from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .hyperliquid_client import HyperliquidInfoClient
from .models import Asset, Candidate, Snapshot
from .timeutil import now_ms


def parse_perp_asset_list(meta: dict[str, Any]) -> list[Asset]:
    universe = meta.get("universe")
    if not isinstance(universe, list):
        raise ValueError("Perp metadata is missing universe list")
    assets: list[Asset] = []
    for index, item in enumerate(universe):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or index)
        asset_id = str(item.get("assetId") or item.get("index") or index)
        assets.append(Asset("perp", asset_id, name, item))
    return assets


def parse_perp_assets(meta: dict[str, Any]) -> dict[str, Asset]:
    return {asset.key: asset for asset in parse_perp_asset_list(meta)}


def parse_spot_asset_list(meta: dict[str, Any]) -> list[Asset]:
    universe = meta.get("universe")
    tokens = meta.get("tokens")
    if not isinstance(universe, list):
        raise ValueError("Spot metadata is missing universe list")
    token_names: dict[int, str] = {}
    if isinstance(tokens, list):
        for token in tokens:
            if isinstance(token, dict) and "index" in token:
                token_names[int(token["index"])] = str(token.get("name") or token["index"])

    assets: list[Asset] = []
    for index, item in enumerate(universe):
        if not isinstance(item, dict):
            continue
        pair = item.get("tokens")
        if isinstance(pair, list) and len(pair) >= 2:
            base = token_names.get(int(pair[0]), str(pair[0]))
            quote = token_names.get(int(pair[1]), str(pair[1]))
            symbol = f"{base}/{quote}"
        else:
            symbol = str(item.get("name") or index)
        asset_id = str(item.get("index") or item.get("assetId") or index)
        assets.append(Asset("spot", asset_id, symbol, item))
    return assets


def parse_spot_assets(meta: dict[str, Any]) -> dict[str, Asset]:
    return {asset.key: asset for asset in parse_spot_asset_list(meta)}


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class MetadataWatcher:
    def __init__(self, client: HyperliquidInfoClient, markets: tuple[str, ...]) -> None:
        self.client = client
        self.markets = markets

    def fetch_snapshot(self) -> Snapshot:
        all_assets: dict[str, Asset] = {}
        raw: dict[str, Any] = {}
        total_latency_ms = 0.0

        if "perp" in self.markets:
            meta, latency_ms = self.client.perp_meta()
            if not isinstance(meta, dict):
                raise ValueError("Unexpected perp metadata response")
            raw["perp"] = meta
            total_latency_ms += latency_ms
            all_assets.update(parse_perp_assets(meta))

        if "spot" in self.markets:
            meta, latency_ms = self.client.spot_meta()
            if not isinstance(meta, dict):
                raise ValueError("Unexpected spot metadata response")
            raw["spot"] = meta
            total_latency_ms += latency_ms
            all_assets.update(parse_spot_assets(meta))

        return Snapshot(
            assets=all_assets,
            fetched_at_ms=now_ms(),
            latency_ms=total_latency_ms,
            raw_hash=_stable_hash(raw),
        )


class BaselineStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load_keys(self) -> set[str]:
        if not self.path.exists():
            return set()
        with self.path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        keys = data.get("asset_keys", [])
        if not isinstance(keys, list):
            raise ValueError("Baseline file has invalid asset_keys")
        return {str(key) for key in keys}

    def save(self, snapshot: Snapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fetched_at_ms": snapshot.fetched_at_ms,
            "raw_hash": snapshot.raw_hash,
            "asset_keys": sorted(snapshot.assets),
            "assets": {
                key: {
                    "market_type": asset.market_type,
                    "asset_id": asset.asset_id,
                    "symbol": asset.symbol,
                }
                for key, asset in sorted(snapshot.assets.items())
            },
        }
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")


def diff_new_assets(previous_keys: set[str], snapshot: Snapshot) -> list[Candidate]:
    candidates: list[Candidate] = []
    for key, asset in sorted(snapshot.assets.items()):
        if key not in previous_keys:
            candidates.append(
                Candidate(
                    asset=asset,
                    discovered_at_ms=snapshot.fetched_at_ms,
                    reason="asset key was absent from baseline",
                )
            )
    return candidates
