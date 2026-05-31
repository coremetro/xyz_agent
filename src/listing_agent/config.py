from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import os
from typing import Any


def _csv_set(value: str) -> set[str]:
    return {item.strip().upper() for item in value.split(",") if item.strip()}


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv_or_list(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return _csv_set(value)
    if isinstance(value, list):
        return {str(item).strip().upper() for item in value if str(item).strip()}
    raise ValueError("Expected string or list for asset list")


def _load_config_file(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Config file must contain a JSON object")
    return data


def _get(data: dict[str, Any], key: str, default: Any) -> Any:
    return data[key] if key in data else default


def _get_path(data: dict[str, Any], key: str, default: str) -> Path:
    return Path(str(_get(data, key, default)))


@dataclass(frozen=True)
class AgentConfig:
    api_url: str = "https://api.hyperliquid.xyz/info"
    markets: tuple[str, ...] = ("perp", "spot")
    poll_interval_ms: int = 1_500
    once: bool = False
    dry_run: bool = True
    baseline_path: Path = Path("state/baseline.json")
    audit_log_path: Path = Path("logs/audit.jsonl")
    stop_file_path: Path = Path("state/STOP")
    max_notional_usd: float = 25.0
    max_total_exposure_usd: float = 25.0
    max_daily_loss_usd: float = 10.0
    min_order_notional_usd: float = 10.0
    slippage_bps: float = 50.0
    live_trading_ack: str = ""
    live_base_url: str = "https://api.hyperliquid.xyz"
    account_address: str = ""
    secret_key: str = ""
    min_context_freshness_ms: int = 10_000
    allowlist: set[str] = field(default_factory=set)
    denylist: set[str] = field(default_factory=set)

    @classmethod
    def from_env(cls, config_path: Path | None = None) -> "AgentConfig":
        file_config = _load_config_file(config_path)
        markets = tuple(
            market.strip().lower()
            for market in str(_get(file_config, "markets", os.getenv("AGENT_MARKETS", "perp,spot"))).split(",")
            if market.strip()
        )
        return cls(
            api_url=str(_get(file_config, "api_url", os.getenv("HYPERLIQUID_INFO_URL", cls.api_url))),
            markets=markets or cls.markets,
            poll_interval_ms=int(_get(file_config, "poll_interval_ms", os.getenv("POLL_INTERVAL_MS", "1500"))),
            once=bool(_get(file_config, "once", _bool_env("RUN_ONCE", False))),
            dry_run=bool(_get(file_config, "dry_run", _bool_env("DRY_RUN", True))),
            baseline_path=_get_path(file_config, "baseline_path", os.getenv("BASELINE_PATH", "state/baseline.json")),
            audit_log_path=_get_path(file_config, "audit_log_path", os.getenv("AUDIT_LOG_PATH", "logs/audit.jsonl")),
            stop_file_path=_get_path(file_config, "stop_file_path", os.getenv("STOP_FILE_PATH", "state/STOP")),
            max_notional_usd=float(_get(file_config, "max_notional_usd", os.getenv("MAX_NOTIONAL_USD", "25"))),
            max_total_exposure_usd=float(
                _get(file_config, "max_total_exposure_usd", os.getenv("MAX_TOTAL_EXPOSURE_USD", "25"))
            ),
            max_daily_loss_usd=float(_get(file_config, "max_daily_loss_usd", os.getenv("MAX_DAILY_LOSS_USD", "10"))),
            min_order_notional_usd=float(_get(file_config, "min_order_notional_usd", os.getenv("MIN_ORDER_NOTIONAL_USD", "10"))),
            slippage_bps=float(_get(file_config, "slippage_bps", os.getenv("SLIPPAGE_BPS", "50"))),
            live_trading_ack=os.getenv("LIVE_TRADING_ACK", ""),
            live_base_url=str(_get(file_config, "live_base_url", os.getenv("HYPERLIQUID_BASE_URL", "https://api.hyperliquid.xyz"))),
            account_address=os.getenv("HYPERLIQUID_ACCOUNT_ADDRESS", ""),
            secret_key=os.getenv("HYPERLIQUID_SECRET_KEY", ""),
            min_context_freshness_ms=int(
                _get(file_config, "min_context_freshness_ms", os.getenv("MIN_CONTEXT_FRESHNESS_MS", "10000"))
            ),
            allowlist=_csv_or_list(_get(file_config, "asset_allowlist", os.getenv("ASSET_ALLOWLIST", ""))),
            denylist=_csv_or_list(_get(file_config, "asset_denylist", os.getenv("ASSET_DENYLIST", ""))),
        )

    def validate(self) -> None:
        if not self.dry_run:
            expected_ack = "I_UNDERSTAND_THIS_PLACES_REAL_ORDERS"
            if self.live_trading_ack != expected_ack:
                raise ValueError(f"Live mode requires LIVE_TRADING_ACK={expected_ack}")
            missing = []
            if self.max_notional_usd <= 0:
                missing.append("MAX_NOTIONAL_USD")
            if self.max_total_exposure_usd <= 0:
                missing.append("MAX_TOTAL_EXPOSURE_USD")
            if self.max_daily_loss_usd <= 0:
                missing.append("MAX_DAILY_LOSS_USD")
            if self.min_order_notional_usd <= 0:
                missing.append("MIN_ORDER_NOTIONAL_USD")
            if self.slippage_bps <= 0:
                missing.append("SLIPPAGE_BPS")
            if not self.account_address:
                missing.append("HYPERLIQUID_ACCOUNT_ADDRESS")
            if not self.secret_key:
                missing.append("HYPERLIQUID_SECRET_KEY")
            if missing:
                joined = ", ".join(missing)
                raise ValueError(f"Live mode requires these configured values: {joined}")
            if self.stop_file_path.exists():
                raise ValueError(f"Kill switch is active because stop file exists: {self.stop_file_path}")
            if self.max_notional_usd > self.max_total_exposure_usd:
                raise ValueError("MAX_NOTIONAL_USD cannot exceed MAX_TOTAL_EXPOSURE_USD")
        unknown = set(self.markets) - {"perp", "spot"}
        if unknown:
            raise ValueError(f"Unsupported market types: {sorted(unknown)}")
