from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .audit import AuditLogger
from .config import AgentConfig
from .execution import ExecutionAdapter, HyperliquidLiveExecutionAdapter
from .hyperliquid_client import HyperliquidInfoClient
from .metadata import BaselineStore, MetadataWatcher, diff_new_assets
from .models import Asset, Candidate, MarketCheck
from .risk import RiskEngine
from .timeutil import now_ms
from .validator import MarketValidator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monitor trade.xyz / Hyperliquid listings in dry-run mode.")
    parser.add_argument("--config", default="config/settings.json", help="JSON config file path.")
    subparsers = parser.add_subparsers(dest="command")

    buy_parser = subparsers.add_parser("buy", help="Submit one real perp buy using config guardrails.")
    buy_parser.add_argument("symbol", help="Perp symbol, for example BTC.")
    buy_parser.add_argument("--notional", type=float, help="Requested USD notional. Must be <= config limits.")
    buy_parser.add_argument("--yes", action="store_true", help="Confirm this can place a real order.")

    close_parser = subparsers.add_parser("close", help="Close an existing perp position using reduce-only order.")
    close_parser.add_argument("symbol", help="Perp symbol, for example BTC.")
    close_parser.add_argument("--yes", action="store_true", help="Confirm this can place a real reduce-only order.")

    preflight_parser = subparsers.add_parser("preflight", help="Run a read-only live account preflight.")
    preflight_parser.add_argument("symbol", nargs="?", default="BTC", help="Symbol to check. Defaults to BTC.")

    parser.add_argument("--once", action="store_true", help="Run one poll and exit.")
    parser.add_argument("--init-baseline", action="store_true", help="Save current assets as the baseline and exit.")
    parser.add_argument(
        "--simulate-order",
        metavar="SYMBOL",
        help="Create one dry-run buy order intent for a simulated listing symbol and exit.",
    )
    parser.add_argument(
        "--simulate-market",
        choices=("perp", "spot"),
        default="perp",
        help="Market type for --simulate-order. Defaults to perp.",
    )
    parser.add_argument(
        "--simulate-asset-id",
        default="simulated",
        help="Stable asset id for --simulate-order. Defaults to simulated.",
    )
    parser.add_argument(
        "--live-buy",
        metavar="SYMBOL",
        help="Submit one real perp marketable-limit buy through Hyperliquid SDK and exit.",
    )
    parser.add_argument(
        "--live-preflight",
        nargs="?",
        const="BTC",
        metavar="SYMBOL",
        help="Run a read-only live credential/account preflight for SYMBOL without placing an order.",
    )
    parser.add_argument(
        "--i-understand-live-order",
        action="store_true",
        help="Required with --live-buy; confirms this command can place a real order.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = Path(args.config)
    config = AgentConfig.from_env(config_path if config_path.exists() else None)
    if args.once:
        config = _replace_once(config)

    audit = AuditLogger(config.audit_log_path)
    client = HyperliquidInfoClient(config.api_url)
    watcher = MetadataWatcher(client, config.markets)
    store = BaselineStore(config.baseline_path)
    validator = MarketValidator(client, config)
    risk = RiskEngine(config)
    execution = ExecutionAdapter()

    try:
        config.validate()
        audit.write("agent_started", {"dry_run": config.dry_run, "markets": config.markets})

        if args.command == "preflight":
            return run_live_preflight(args.symbol, config, audit)

        if args.command == "buy":
            return run_live_buy(args.symbol, args.yes, config, audit, args.notional)

        if args.command == "close":
            return run_live_close(args.symbol, args.yes, config, audit)

        if args.simulate_order:
            return run_simulated_order(args.simulate_order, args.simulate_market, args.simulate_asset_id, config, audit)

        if args.live_preflight:
            return run_live_preflight(args.live_preflight, config, audit)

        if args.live_buy:
            return run_live_buy(args.live_buy, args.i_understand_live_order, config, audit)

        if args.init_baseline:
            snapshot = watcher.fetch_snapshot()
            store.save(snapshot)
            audit.write("baseline_initialized", {"asset_count": len(snapshot.assets), "raw_hash": snapshot.raw_hash})
            print(f"Initialized baseline with {len(snapshot.assets)} assets at {config.baseline_path}")
            return 0

        while True:
            previous_keys = store.load_keys()
            snapshot = watcher.fetch_snapshot()
            candidates = diff_new_assets(previous_keys, snapshot)
            audit.write(
                "snapshot_fetched",
                {
                    "asset_count": len(snapshot.assets),
                    "new_count": len(candidates),
                    "latency_ms": round(snapshot.latency_ms, 3),
                    "raw_hash": snapshot.raw_hash,
                },
            )

            if not previous_keys:
                audit.write("baseline_missing", {"action": "saving snapshot without trading"})
                store.save(snapshot)
                print(f"Saved initial baseline with {len(snapshot.assets)} assets; no trades considered.")
            else:
                for candidate in candidates:
                    audit.write("candidate_discovered", {"candidate": candidate})
                    market_check = validator.validate(candidate)
                    audit.write("candidate_validated", {"asset_key": candidate.asset.key, "check": market_check})
                    if not market_check.approved:
                        continue
                    intent = risk.create_buy_intent(candidate, market_check)
                    audit.write("order_intent_created", {"intent": intent})
                    result = execution.submit(intent)
                    audit.write("order_submission_result", {"result": result})
                    print(f"DRY RUN order intent: buy ${intent.notional_usd:g} of {intent.symbol}")
                store.save(snapshot)

            if config.once:
                return 0
            time.sleep(config.poll_interval_ms / 1000)
    except KeyboardInterrupt:
        audit.write("agent_stopped", {"reason": "keyboard_interrupt"})
        return 130
    except Exception as exc:
        audit.write("agent_error", {"error": str(exc)})
        print(f"error: {exc}", file=sys.stderr)
        return 1


def run_simulated_order(
    symbol: str,
    market_type: str,
    asset_id: str,
    config: AgentConfig,
    audit: AuditLogger,
) -> int:
    if not config.dry_run:
        raise ValueError("--simulate-order only runs when DRY_RUN=true")

    asset = Asset(
        market_type=market_type,
        asset_id=asset_id,
        symbol=symbol,
        raw={"source": "manual_simulation"},
    )
    candidate = Candidate(
        asset=asset,
        discovered_at_ms=now_ms(),
        reason="manual dry-run order simulation",
    )
    market_check = MarketCheck(
        approved=True,
        reason="manual simulation bypassed network context checks",
        context={"source": "manual_simulation"},
    )
    risk = RiskEngine(config)
    execution = ExecutionAdapter()
    audit.write("candidate_discovered", {"candidate": candidate})
    audit.write("candidate_validated", {"asset_key": candidate.asset.key, "check": market_check})
    intent = risk.create_buy_intent(candidate, market_check)
    audit.write("order_intent_created", {"intent": intent})
    result = execution.submit(intent)
    audit.write("order_submission_result", {"result": result})
    print(
        "DRY RUN simulated order intent: "
        f"buy ${intent.notional_usd:g} of {intent.symbol} "
        f"({intent.asset_key}, {intent.order_type})"
    )
    print(f"idempotency_key={intent.idempotency_key}")
    return 0


def run_live_buy(
    symbol: str,
    confirmed: bool,
    config: AgentConfig,
    audit: AuditLogger,
    notional_usd: float | None = None,
) -> int:
    if config.dry_run:
        raise ValueError("Live buy requires DRY_RUN=false")
    if not confirmed:
        raise ValueError("--live-buy requires --i-understand-live-order")
    config.validate()

    candidate = Candidate(
        asset=Asset(
            market_type="perp",
            asset_id=symbol,
            symbol=symbol.upper(),
            raw={"source": "manual_live_buy"},
        ),
        discovered_at_ms=now_ms(),
        reason="manual live buy test",
    )
    market_check = MarketCheck(
        approved=True,
        reason="manual live order; Hyperliquid SDK will validate symbol and price",
        context={"source": "manual_live_buy"},
    )
    risk = RiskEngine(config)
    intent = risk.create_buy_intent(candidate, market_check, notional_usd)
    audit.write("live_order_intent_created", {"intent": intent})
    result = HyperliquidLiveExecutionAdapter(config).submit_market_buy(intent)
    audit.write("live_order_submission_result", {"result": result})
    print(f"LIVE order submitted: buy ${intent.notional_usd:g} of {intent.symbol}")
    print(f"result_status={result.get('status')}")
    return 0


def run_live_preflight(symbol: str, config: AgentConfig, audit: AuditLogger) -> int:
    if config.dry_run:
        raise ValueError("Live preflight requires DRY_RUN=false")
    config.validate()
    result = HyperliquidLiveExecutionAdapter(config).preflight(symbol)
    audit.write("live_preflight_result", {"result": result})
    print("LIVE preflight OK")
    print(f"account_address={result['account_address']}")
    print(f"address_matches_secret={result['address_matches_secret']}")
    print(f"symbol={result['symbol']} symbol_has_mid={result['symbol_has_mid']}")
    print(f"account_value={result['account_value']}")
    print(f"withdrawable={result['withdrawable']}")
    return 0


def run_live_close(symbol: str, confirmed: bool, config: AgentConfig, audit: AuditLogger) -> int:
    if config.dry_run:
        raise ValueError("Live close requires DRY_RUN=false")
    if not confirmed:
        raise ValueError("close requires --yes")
    config.validate()
    result = HyperliquidLiveExecutionAdapter(config).close_position(symbol)
    audit.write("live_close_submission_result", {"result": result})
    print(f"LIVE close submitted: {result['symbol']} size={result['closed_size']}")
    print(f"result_status={result.get('status')}")
    return 0


def _replace_once(config: AgentConfig) -> AgentConfig:
    return AgentConfig(
        api_url=config.api_url,
        markets=config.markets,
        poll_interval_ms=config.poll_interval_ms,
        once=True,
        dry_run=config.dry_run,
        baseline_path=config.baseline_path,
        audit_log_path=config.audit_log_path,
        stop_file_path=config.stop_file_path,
        max_notional_usd=config.max_notional_usd,
        max_total_exposure_usd=config.max_total_exposure_usd,
        max_daily_loss_usd=config.max_daily_loss_usd,
        min_order_notional_usd=config.min_order_notional_usd,
        slippage_bps=config.slippage_bps,
        live_trading_ack=config.live_trading_ack,
        live_base_url=config.live_base_url,
        account_address=config.account_address,
        secret_key=config.secret_key,
        min_context_freshness_ms=config.min_context_freshness_ms,
        allowlist=config.allowlist,
        denylist=config.denylist,
    )


if __name__ == "__main__":
    raise SystemExit(main())
