from __future__ import annotations

import hashlib
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from .config import AgentConfig
from .models import OrderIntent


class ExecutionAdapter:
    def submit(self, intent: OrderIntent) -> dict[str, object]:
        if intent.dry_run:
            return {
                "status": "dry_run",
                "submitted": False,
                "intent": intent,
            }
        raise RuntimeError(
            "Live execution is intentionally disabled in this scaffold. "
            "Add a signed exchange adapter only after explicit approval, jurisdiction review, "
            "credential setup, and live risk limits."
        )


class HyperliquidLiveExecutionAdapter:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def submit_market_buy(self, intent: OrderIntent) -> dict[str, object]:
        if intent.dry_run:
            raise ValueError("Live adapter received a dry-run intent")
        if self.config.stop_file_path.exists():
            raise RuntimeError(f"Kill switch is active: {self.config.stop_file_path}")

        try:
            import eth_account
            from hyperliquid.exchange import Exchange
            from hyperliquid.info import Info
            from hyperliquid.utils.types import Cloid
        except ImportError as exc:
            raise RuntimeError(
                "Live trading requires optional dependencies. "
                "Install with: python -m pip install -e '.[live]'"
            ) from exc

        account = eth_account.Account.from_key(self.config.secret_key)
        info = Info(self.config.live_base_url, skip_ws=True)
        exchange = Exchange(
            account,
            self.config.live_base_url,
            account_address=self.config.account_address,
        )
        mids = info.all_mids()
        symbol = intent.symbol.upper()
        if symbol not in mids:
            raise ValueError(f"Symbol {intent.symbol!r} was not found in Hyperliquid all_mids")
        mid_px = float(mids[symbol])
        if mid_px <= 0:
            raise ValueError(f"Invalid mid price for {intent.symbol}: {mid_px}")

        sz_decimals = _sz_decimals(info, symbol)
        size = _size_at_or_below_notional(intent.notional_usd, mid_px, sz_decimals)
        estimated_notional = size * mid_px
        if estimated_notional < self.config.min_order_notional_usd:
            min_size = _size_for_notional(self.config.min_order_notional_usd, mid_px, sz_decimals)
            min_adjusted_notional = min_size * mid_px
            raise ValueError(
                "Requested notional is too small after size-step rounding. "
                f"requested={intent.notional_usd:g}, rounded_down={estimated_notional:g}, "
                f"minimum={self.config.min_order_notional_usd:g}, "
                f"minimum_step_notional={min_adjusted_notional:g}, sz_decimals={sz_decimals}. "
                "Increase --notional."
            )
        if estimated_notional > self.config.max_total_exposure_usd:
            raise ValueError(
                "Order size step pushes notional above MAX_TOTAL_EXPOSURE_USD. "
                f"requested={intent.notional_usd:g}, adjusted={estimated_notional:g}, "
                f"sz_decimals={sz_decimals}"
            )
        cloid = Cloid.from_str(_cloid_from_key(intent.idempotency_key))
        slippage = self.config.slippage_bps / 10_000
        result = exchange.market_open(
            symbol,
            True,
            size,
            None,
            slippage,
            cloid=cloid,
        )
        return {
            "status": "submitted",
            "submitted": True,
            "symbol": symbol,
            "notional_usd": intent.notional_usd,
            "estimated_size": _wire_decimal(size),
            "estimated_notional_usd": estimated_notional,
            "min_order_notional_usd": self.config.min_order_notional_usd,
            "mid_px": mid_px,
            "sz_decimals": sz_decimals,
            "slippage_bps": self.config.slippage_bps,
            "cloid": str(cloid),
            "exchange_result": result,
        }

    def close_position(self, symbol: str) -> dict[str, object]:
        if self.config.stop_file_path.exists():
            raise RuntimeError(f"Kill switch is active: {self.config.stop_file_path}")

        try:
            import eth_account
            from hyperliquid.exchange import Exchange
            from hyperliquid.info import Info
            from hyperliquid.utils.types import Cloid
        except ImportError as exc:
            raise RuntimeError(
                "Live trading requires optional dependencies. "
                "Install with: python -m pip install -e '.[live]'"
            ) from exc

        symbol = symbol.upper()
        account = eth_account.Account.from_key(self.config.secret_key)
        info = Info(self.config.live_base_url, skip_ws=True)
        exchange = Exchange(
            account,
            self.config.live_base_url,
            account_address=self.config.account_address,
        )
        position = _open_position(info, self.config.account_address, symbol)
        if position is None:
            raise ValueError(f"No open {symbol} position to close")
        signed_size = float(position["szi"])
        size = abs(signed_size)
        if size <= 0:
            raise ValueError(f"No non-zero {symbol} position to close")
        slippage = self.config.slippage_bps / 10_000
        cloid = Cloid.from_str(_cloid_from_key(f"close:{symbol}:{position.get('time', '')}:{signed_size}"))
        result = exchange.market_close(symbol, size, None, slippage, cloid=cloid)
        return {
            "status": "submitted",
            "submitted": True,
            "symbol": symbol,
            "closed_size": _wire_decimal(size),
            "previous_signed_size": _wire_decimal(signed_size),
            "slippage_bps": self.config.slippage_bps,
            "cloid": str(cloid),
            "exchange_result": result,
        }

    def preflight(self, symbol: str = "BTC") -> dict[str, object]:
        if self.config.stop_file_path.exists():
            raise RuntimeError(f"Kill switch is active: {self.config.stop_file_path}")

        try:
            import eth_account
            from hyperliquid.info import Info
        except ImportError as exc:
            raise RuntimeError(
                "Live trading requires optional dependencies. "
                "Install with: python -m pip install -e '.[live]'"
            ) from exc

        account = eth_account.Account.from_key(self.config.secret_key)
        derived_address = account.address.lower()
        configured_address = self.config.account_address.lower()
        address_matches = derived_address == configured_address
        if not address_matches:
            raise ValueError("HYPERLIQUID_SECRET_KEY does not derive HYPERLIQUID_ACCOUNT_ADDRESS")

        info = Info(self.config.live_base_url, skip_ws=True)
        mids = info.all_mids()
        user_state = info.user_state(self.config.account_address)
        margin_summary = user_state.get("marginSummary", {}) if isinstance(user_state, dict) else {}
        withdrawable = user_state.get("withdrawable") if isinstance(user_state, dict) else None
        return {
            "address_matches_secret": True,
            "account_address": self.config.account_address,
            "symbol": symbol.upper(),
            "symbol_has_mid": symbol.upper() in mids,
            "account_value": margin_summary.get("accountValue"),
            "total_margin_used": margin_summary.get("totalMarginUsed"),
            "withdrawable": withdrawable,
        }


def _cloid_from_key(key: str) -> str:
    return "0x" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _open_position(info: object, account_address: str, symbol: str) -> dict[str, object] | None:
    user_state = info.user_state(account_address)
    positions = user_state.get("assetPositions", []) if isinstance(user_state, dict) else []
    for entry in positions:
        if not isinstance(entry, dict):
            continue
        position = entry.get("position")
        if not isinstance(position, dict):
            continue
        if position.get("coin") == symbol and float(position.get("szi", 0)) != 0:
            return position
    return None


def _sz_decimals(info: object, symbol: str) -> int:
    coin = info.name_to_coin[symbol]
    asset = info.coin_to_asset[coin]
    return int(info.asset_to_sz_decimals[asset])


def _size_for_notional(notional_usd: float, mid_px: float, sz_decimals: int) -> float:
    raw_size = Decimal(str(notional_usd)) / Decimal(str(mid_px))
    step = Decimal(1).scaleb(-sz_decimals)
    rounded = raw_size.quantize(step, rounding=ROUND_CEILING)
    return float(rounded)


def _size_at_or_below_notional(notional_usd: float, mid_px: float, sz_decimals: int) -> float:
    raw_size = Decimal(str(notional_usd)) / Decimal(str(mid_px))
    step = Decimal(1).scaleb(-sz_decimals)
    rounded = raw_size.quantize(step, rounding=ROUND_FLOOR)
    return float(rounded)


def _wire_decimal(value: float) -> str:
    return format(Decimal(str(value)).normalize(), "f")
