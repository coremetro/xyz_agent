# Trade XYZ Listing Agent

Dry-run first monitor for newly listed assets on trade.xyz / Hyperliquid-connected markets.

This is not financial advice. Live trading can lose money quickly. Confirm platform availability, legal compliance, and tax obligations in your jurisdiction before using any live trading system.

## What It Does

- Builds a local baseline from official Hyperliquid metadata.
- Polls `meta` and `spotMeta` through the official info endpoint.
- Detects asset keys that were absent from the baseline.
- Re-fetches fresh market context before creating any order intent.
- Defaults to `DRY_RUN=true`; live execution is intentionally disabled in this scaffold.
- Writes audit records to `logs/audit.jsonl`.

## Run

```bash
cd trade_xyz_listing_agent
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cp config/settings.example.json config/settings.json
scripts/trade --init-baseline
scripts/trade --once
```

The first normal run also initializes a baseline and will not trade. A later run only creates dry-run order intents when it sees an asset key that was not in the saved baseline.

See `docs/PROJECT_STRUCTURE.md` for the analysis, monitoring, and trading module layout.
See `docs/TEST_PLAN.md` for the shortest validation path.
See `docs/DEPLOYMENT.md` for cloud server deployment.

## Test The Order Path

Run a dry-run order simulation without network access or credentials:

```bash
MAX_NOTIONAL_USD=5 scripts/trade --simulate-order TEST --simulate-market perp --simulate-asset-id 999
```

This writes the same audit events as a discovered listing would, but it never submits a live order. The command refuses to run when `DRY_RUN=false`.

## Live Small-Order Test

Live mode uses the official `hyperliquid-python-sdk`. Install the optional dependency first:

```bash
python -m pip install -e '.[live]'
```

Then set credentials and explicit live-trading limits through environment variables. Do not paste private keys into chat or commit them to files:
Risk limits should usually live in `config/settings.json`; secrets still come from environment variables.

Example `config/settings.json`:

```json
{
  "dry_run": false,
  "markets": "perp",
  "poll_interval_ms": 1500,
  "baseline_path": "state/baseline.json",
  "audit_log_path": "logs/audit.jsonl",
  "stop_file_path": "state/STOP",
  "max_notional_usd": 5,
  "max_total_exposure_usd": 10,
  "max_daily_loss_usd": 5,
  "slippage_bps": 50,
  "asset_allowlist": [],
  "asset_denylist": []
}
```

Keep credentials and the live acknowledgement in environment variables:

```bash
export HYPERLIQUID_ACCOUNT_ADDRESS="0x..."
export HYPERLIQUID_SECRET_KEY="0x..."
export LIVE_TRADING_ACK="I_UNDERSTAND_THIS_PLACES_REAL_ORDERS"
```

Submit one manual perp buy test:

First run a read-only preflight. It checks the SDK, derives the wallet address from the private key, reads account state, and does not place an order:

```bash
scripts/trade preflight BTC
```

Then submit one manual perp buy test:

```bash
scripts/trade buy BTC --notional 10 --yes
```

`--notional` can be lower than the configured `max_notional_usd`, but it cannot exceed `max_notional_usd` or `max_total_exposure_usd`.

Close an existing perp position with a reduce-only marketable-limit order:

```bash
scripts/trade close BTC --yes
```

The default kill switch is `state/STOP`: if that file exists, live mode refuses to run. Create it to stop live trading immediately:

```bash
touch state/STOP
```

Live listing-triggered auto-buying is still disabled in this scaffold; only the explicit `--live-buy` command can submit a real order.

## Configuration

Environment variables:

- `DRY_RUN`: fallback for `dry_run` when no config file value is present.
- `AGENT_MARKETS`: fallback for `markets` when no config file value is present.
- `POLL_INTERVAL_MS`: fallback for `poll_interval_ms` when no config file value is present.
- `MAX_NOTIONAL_USD`: fallback for `max_notional_usd` when no config file value is present.
- `MAX_TOTAL_EXPOSURE_USD`: fallback for `max_total_exposure_usd` when no config file value is present.
- `MAX_DAILY_LOSS_USD`: fallback for `max_daily_loss_usd` when no config file value is present.
- `SLIPPAGE_BPS`: fallback for `slippage_bps` when no config file value is present.
- `LIVE_TRADING_ACK`: must be `I_UNDERSTAND_THIS_PLACES_REAL_ORDERS` when `DRY_RUN=false`.
- `HYPERLIQUID_ACCOUNT_ADDRESS`: main account address for live mode.
- `HYPERLIQUID_SECRET_KEY`: API wallet or account private key for live mode.
- `STOP_FILE_PATH`: fallback for `stop_file_path` when no config file value is present.
- `ASSET_ALLOWLIST`: fallback for `asset_allowlist` when no config file value is present.
- `ASSET_DENYLIST`: fallback for `asset_denylist` when no config file value is present.
- `BASELINE_PATH`: fallback for `baseline_path` when no config file value is present.
- `AUDIT_LOG_PATH`: fallback for `audit_log_path` when no config file value is present.

## Development

```bash
scripts/test
```

## Listing Performance Analysis

Generate a read-only report for current perp assets across all perp dexes, including `xyz:*` markets:

```bash
scripts/analyze --config config/settings.json --output-dir reports
```

Quick sample:

```bash
scripts/analyze --symbols BTC,ETH,SOL --output-dir reports/sample
```

Analyze a trade.xyz / XYZ market by suffix or full symbol:

```bash
scripts/analyze --symbols CBRS --output-dir reports/cbrs
scripts/analyze --symbols xyz:CBRS --output-dir reports/cbrs
```

Analyze all trade.xyz / XYZ TradFi markets:

```bash
scripts/analyze-xyz --resume
```

Analyze only the single-name stock-like subset in XYZ:

```bash
scripts/analyze-xyz-stocks --resume
```

After changing analysis rules, validate a few symbols first instead of recomputing the full universe:

```bash
scripts/analyze-xyz --symbols BB,QNT,CBRS --output-dir reports/test_windows
```

Restrict analysis to the core Hyperliquid perp universe:

```bash
scripts/analyze --universe core --output-dir reports/core
```

Resume an interrupted all-asset run:

```bash
scripts/analyze --output-dir reports/all --resume
```

Retry only failed rows from an interrupted run:

```bash
scripts/analyze --output-dir reports/all --resume --retry-errors
```

Refresh older resumed rows that do not yet include volume fields:

```bash
scripts/analyze --output-dir reports/all --resume --refresh-missing-volume
```

Outputs:

- `listing_performance.csv`
- `listing_performance.json`
- `data_quality.csv`
- `summary_performance.csv`
- `summary_performance.json`

`listing_performance.csv` contains only performance values. Data source, listing confidence, and window status such as `ok`, `late`, and `missing` live in `data_quality.csv`. `late` windows are not included in return calculations.

The report uses Hyperliquid `candleSnapshot` and computes windows `1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 8h, 12h, 1d, 3d, 1w`. Official candle snapshots return only the most recent 5000 candles, so `listing_confidence=truncated` means the observed first candle may not be the real listing time. Future listings detected by the watcher should be treated as more precise than reconstructed historical listings.

## New Asset Monitor

The monitor module implements the first MVP from the PRD: detect new XYZ assets, verify market readiness, score the opportunity, persist events/snapshots locally, and optionally send a webhook alert. It does not submit orders.

Initialize the current XYZ universe as the monitor baseline:

```bash
scripts/monitor-xyz --init-baseline
```

Run one metadata diff check:

```bash
scripts/monitor-xyz --once
```

Run continuously:

```bash
scripts/monitor-xyz --poll-interval 2
```

Run continuously with WebSocket `allMids` key detection:

```bash
scripts/monitor-xyz --poll-interval 2 --with-ws
```

Verify one ticker manually:

```bash
scripts/monitor-xyz --verify xyz:BB
```

Local monitor files:

- `state/monitor/assets.json`
- `state/monitor/asset_events.jsonl`
- `state/monitor/asset_snapshots.jsonl`
- `state/monitor/alerts.jsonl`
