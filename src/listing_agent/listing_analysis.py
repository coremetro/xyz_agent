from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .hyperliquid_client import HyperliquidInfoClient


INTERVAL_MS = {
    "1m": 60_000,
    "3m": 3 * 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 3_600_000,
    "2h": 2 * 3_600_000,
    "4h": 4 * 3_600_000,
    "8h": 8 * 3_600_000,
    "12h": 12 * 3_600_000,
    "1d": 86_400_000,
    "3d": 3 * 86_400_000,
    "1w": 7 * 86_400_000,
}

PERFORMANCE_WINDOWS = (
    ("1m", 60_000),
    ("3m", 3 * 60_000),
    ("5m", 5 * 60_000),
    ("15m", 15 * 60_000),
    ("30m", 30 * 60_000),
    ("1h", 60 * 60_000),
    ("2h", 2 * 60 * 60_000),
    ("4h", 4 * 60 * 60_000),
    ("8h", 8 * 60 * 60_000),
    ("12h", 12 * 60 * 60_000),
    ("1d", 24 * 60 * 60_000),
    ("3d", 3 * 24 * 60 * 60_000),
    ("1w", 7 * 24 * 60 * 60_000),
)

XYZ_STOCK_SUFFIXES = {
    "AAPL",
    "AMD",
    "AMZN",
    "ARM",
    "ASML",
    "BABA",
    "BB",
    "BIRD",
    "BX",
    "CBRS",
    "COIN",
    "COST",
    "CRCL",
    "CRWV",
    "DKNG",
    "DELL",
    "EBAY",
    "GME",
    "GOOGL",
    "HIMS",
    "HOOD",
    "HYUNDAI",
    "INTC",
    "KIOXIA",
    "LITE",
    "LLY",
    "META",
    "MINIMAX",
    "MRVL",
    "MSFT",
    "MSTR",
    "MU",
    "NFLX",
    "NVDA",
    "ORCL",
    "PLTR",
    "QNT",
    "RIVN",
    "RKLB",
    "SKHX",
    "SMSN",
    "SNDK",
    "SOFTBANK",
    "TSLA",
    "TSM",
    "ZM",
}


@dataclass(frozen=True)
class ListingPerformance:
    symbol: str
    listing_time_ms: int | None
    listing_time_utc: str
    listing_source: str
    listing_confidence: str
    open_price: float | None
    results: dict[str, dict[str, Any]]
    notes: str


def analyze_perp_listings(
    client: HyperliquidInfoClient,
    symbols: list[str] | None = None,
    limit: int | None = None,
    sleep_s: float = 0.05,
    universe: str = "all",
    dex: str | None = None,
    category: str = "all",
) -> list[ListingPerformance]:
    all_symbols = discover_perp_symbols(client, universe=universe, symbols=symbols, dex=dex, category=category)
    if limit is not None:
        all_symbols = all_symbols[:limit]

    rows: list[ListingPerformance] = []
    for symbol in all_symbols:
        try:
            rows.append(analyze_symbol(client, symbol))
        except Exception as exc:
            rows.append(_error_row(symbol, exc))
        if sleep_s > 0:
            time.sleep(sleep_s)
    return rows


def discover_perp_symbols(
    client: HyperliquidInfoClient,
    universe: str = "all",
    symbols: list[str] | None = None,
    dex: str | None = None,
    category: str = "all",
) -> list[str]:
    if universe not in {"all", "core"}:
        raise ValueError("universe must be 'all' or 'core'")
    if category not in {"all", "stocks"}:
        raise ValueError("category must be 'all' or 'stocks'")
    if universe == "core":
        meta, _ = client.perp_meta()
        metas_with_names = [(None, meta)]
    else:
        metas, _ = client.post({"type": "allPerpMetas"})
        dexs, _ = client.post({"type": "perpDexs"})
        if not isinstance(metas, list):
            raise ValueError("Unexpected allPerpMetas response")
        if not isinstance(dexs, list):
            raise ValueError("Unexpected perpDexs response")
        metas_with_names = []
        for index, meta in enumerate(metas):
            dex_meta = dexs[index] if index < len(dexs) else None
            dex_name = None if dex_meta is None else str(dex_meta.get("name"))
            metas_with_names.append((dex_name, meta))

    all_symbols: list[str] = []
    for dex_name, meta in metas_with_names:
        if dex is not None and (dex_name or "core").lower() != dex.lower():
            continue
        if not isinstance(meta, dict) or not isinstance(meta.get("universe"), list):
            continue
        for item in meta["universe"]:
            if isinstance(item, dict) and item.get("name"):
                symbol = str(item["name"])
                if category == "stocks" and not _is_stock_symbol(symbol):
                    continue
                all_symbols.append(symbol)

    if symbols:
        wanted = {symbol.upper() for symbol in symbols}
        all_symbols = [
            symbol
            for symbol in all_symbols
            if symbol.upper() in wanted or symbol.upper().split(":")[-1] in wanted
        ]
    return all_symbols


def _is_stock_symbol(symbol: str) -> bool:
    suffix = symbol.upper().split(":")[-1]
    return suffix in XYZ_STOCK_SUFFIXES


def analyze_symbol(client: HyperliquidInfoClient, symbol: str) -> ListingPerformance:
    now_ms = int(time.time() * 1000)
    one_day, _ = client.candles(symbol, "1d", 0, now_ms)
    if not isinstance(one_day, list) or not one_day:
        return ListingPerformance(
            symbol=symbol,
            listing_time_ms=None,
            listing_time_utc="",
            listing_source="1d_candleSnapshot",
            listing_confidence="missing",
            open_price=None,
            results={},
            notes="no 1d candles returned",
        )

    first_daily = min(one_day, key=_candle_start)
    first_daily_t = _candle_start(first_daily)
    daily_truncated = len(one_day) >= 5000

    fine_start = max(0, first_daily_t - INTERVAL_MS["1h"])
    fine_end = min(now_ms, first_daily_t + INTERVAL_MS["1d"] + INTERVAL_MS["1h"])
    one_minute, _ = client.candles(symbol, "1m", fine_start, fine_end)
    listing_source = "1m_candleSnapshot"
    confidence = "observed"
    notes: list[str] = []

    if isinstance(one_minute, list) and one_minute:
        first_candle = min(one_minute, key=_candle_start)
        if len(one_minute) >= 5000:
            confidence = "truncated"
            notes.append("1m candle response hit 5000-candle limit")
    else:
        first_candle = first_daily
        listing_source = "1d_candleSnapshot"
        confidence = "coarse"
        notes.append("1m candles unavailable around first daily candle")

    if daily_truncated:
        confidence = "truncated"
        notes.append("1d candle response hit 5000-candle limit")

    listing_time_ms = _candle_start(first_candle)
    open_price = _open(first_candle)
    results = _window_results(client, symbol, listing_time_ms, open_price, now_ms, daily_candles=one_day)
    return ListingPerformance(
        symbol=symbol,
        listing_time_ms=listing_time_ms,
        listing_time_utc=_iso_utc(listing_time_ms),
        listing_source=listing_source,
        listing_confidence=confidence,
        open_price=open_price,
        results=results,
        notes="; ".join(notes),
    )


def _window_results(
    client: HyperliquidInfoClient,
    symbol: str,
    listing_time_ms: int,
    open_price: float | None,
    now_ms: int,
    daily_candles: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    if open_price is None or open_price <= 0:
        return results

    for label, offset_ms in PERFORMANCE_WINDOWS:
        target = listing_time_ms + offset_ms
        interval = label
        if interval == "1d" and daily_candles:
            interval_candles = daily_candles
        else:
            interval_response, _ = client.candles(symbol, interval, listing_time_ms, min(now_ms, target + INTERVAL_MS[interval]))
            interval_candles = interval_response if isinstance(interval_response, list) else []
        candle = _first_candle_closing_at_or_after(interval_candles, target, INTERVAL_MS[interval])
        source = interval
        if candle is None:
            results[label] = {
                "price": None,
                "return_pct": None,
                "volume": None,
                "trade_count": None,
                "time_utc": "",
                "status": "missing",
                "source_interval": "",
            }
            continue
        price = _close(candle)
        status_tolerance = INTERVAL_MS[interval]
        status = "ok" if _candle_close(candle, INTERVAL_MS[interval]) <= target + status_tolerance else "late"
        if status == "late":
            results[label] = {
                "price": None,
                "return_pct": None,
                "volume": None,
                "trade_count": None,
                "time_utc": _iso_utc(_candle_start(candle)),
                "status": "late",
                "source_interval": source,
            }
            continue
        return_pct = ((price / open_price) - 1) * 100 if price is not None else None
        results[label] = {
            "price": price,
            "return_pct": round(return_pct, 2) if return_pct is not None else None,
            "volume": _float_or_none(candle.get("v")),
            "trade_count": _int_or_none(candle.get("n")),
            "time_utc": _iso_utc(_candle_start(candle)),
            "status": "ok",
            "source_interval": source,
        }
    return results


def write_reports(rows: list[ListingPerformance], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "listing_performance.json"
    csv_path = output_dir / "listing_performance.csv"
    quality_csv_path = output_dir / "data_quality.csv"

    payload = [_row_to_json(row) for row in rows]
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    fieldnames = [
        "symbol",
        "listing_time_utc",
        "open_price",
    ]
    for label, _ in PERFORMANCE_WINDOWS:
        fieldnames.extend(
            [
                f"{label}_price",
                f"{label}_return_pct",
                f"{label}_volume",
                f"{label}_trade_count",
            ]
        )

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            flat = {
                "symbol": row.symbol,
                "listing_time_utc": row.listing_time_utc,
                "open_price": row.open_price,
            }
            for label, _ in PERFORMANCE_WINDOWS:
                result = row.results.get(label, {})
                flat[f"{label}_price"] = result.get("price")
                flat[f"{label}_return_pct"] = result.get("return_pct")
                flat[f"{label}_volume"] = result.get("volume")
                flat[f"{label}_trade_count"] = result.get("trade_count")
            writer.writerow(flat)

    write_quality_report(rows, quality_csv_path)
    write_summary(rows, output_dir)
    return json_path, csv_path


def write_quality_report(rows: list[ListingPerformance], path: Path) -> Path:
    fieldnames = [
        "symbol",
        "listing_time_utc",
        "listing_source",
        "listing_confidence",
        "notes",
    ]
    for label, _ in PERFORMANCE_WINDOWS:
        fieldnames.extend([f"{label}_status", f"{label}_source_interval", f"{label}_time_utc"])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            flat = {
                "symbol": row.symbol,
                "listing_time_utc": row.listing_time_utc,
                "listing_source": row.listing_source,
                "listing_confidence": row.listing_confidence,
                "notes": row.notes,
            }
            for label, _ in PERFORMANCE_WINDOWS:
                result = row.results.get(label, {})
                flat[f"{label}_status"] = result.get("status")
                flat[f"{label}_source_interval"] = result.get("source_interval")
                flat[f"{label}_time_utc"] = result.get("time_utc")
            writer.writerow(flat)
    return path


def write_summary(rows: list[ListingPerformance], output_dir: Path) -> tuple[Path, Path]:
    summary_rows = build_summary(rows)
    json_path = output_dir / "summary_performance.json"
    csv_path = output_dir / "summary_performance.csv"
    json_path.write_text(json.dumps(summary_rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "window",
            "asset_count",
            "valid_count",
            "missing_count",
            "mean_return_pct",
            "median_return_pct",
            "win_rate_pct",
            "min_return_pct",
            "max_return_pct",
            "volume_valid_count",
            "volume_missing_count",
            "mean_volume",
            "median_volume",
            "total_volume",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)
    return json_path, csv_path


def build_summary(rows: list[ListingPerformance]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for label, _ in PERFORMANCE_WINDOWS:
        values: list[float] = []
        volumes: list[float] = []
        for row in rows:
            result = row.results.get(label, {})
            value = result.get("return_pct")
            if isinstance(value, (int, float)):
                values.append(float(value))
            volume = result.get("volume")
            if isinstance(volume, (int, float)):
                volumes.append(float(volume))
        asset_count = len(rows)
        valid_count = len(values)
        volume_valid_count = len(volumes)
        output.append(
            {
                "window": label,
                "asset_count": asset_count,
                "valid_count": valid_count,
                "missing_count": asset_count - valid_count,
                "mean_return_pct": round(statistics.fmean(values), 2) if values else None,
                "median_return_pct": round(statistics.median(values), 2) if values else None,
                "win_rate_pct": round(sum(1 for value in values if value > 0) / valid_count * 100, 2) if values else None,
                "min_return_pct": round(min(values), 2) if values else None,
                "max_return_pct": round(max(values), 2) if values else None,
                "volume_valid_count": volume_valid_count,
                "volume_missing_count": asset_count - volume_valid_count,
                "mean_volume": round(statistics.fmean(volumes), 2) if volumes else None,
                "median_volume": round(statistics.median(volumes), 2) if volumes else None,
                "total_volume": round(sum(volumes), 2) if volumes else None,
            }
        )
    return output


def read_existing_report(path: Path) -> list[ListingPerformance]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Existing report JSON must contain a list")
    rows: list[ListingPerformance] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        rows.append(
            ListingPerformance(
                symbol=str(item.get("symbol", "")),
                listing_time_ms=item.get("listing_time_ms"),
                listing_time_utc=str(item.get("listing_time_utc", "")),
                listing_source=str(item.get("listing_source", "")),
                listing_confidence=str(item.get("listing_confidence", "")),
                open_price=item.get("open_price"),
                results=item.get("results", {}) if isinstance(item.get("results"), dict) else {},
                notes=str(item.get("notes", "")),
            )
        )
    return rows


def _row_has_volume_fields(row: ListingPerformance) -> bool:
    return any(isinstance(result, dict) and "volume" in result for result in row.results.values())


def _row_to_json(row: ListingPerformance) -> dict[str, Any]:
    return {
        "symbol": row.symbol,
        "listing_time_ms": row.listing_time_ms,
        "listing_time_utc": row.listing_time_utc,
        "listing_source": row.listing_source,
        "listing_confidence": row.listing_confidence,
        "open_price": row.open_price,
        "results": row.results,
        "notes": row.notes,
    }


def _error_row(symbol: str, exc: Exception) -> ListingPerformance:
    return ListingPerformance(
        symbol=symbol,
        listing_time_ms=None,
        listing_time_utc="",
        listing_source="",
        listing_confidence="error",
        open_price=None,
        results={},
        notes=str(exc),
    )


def _candle_start(candle: dict[str, Any]) -> int:
    return int(candle.get("t", candle.get("T", 0)))


def _candle_close(candle: dict[str, Any], interval_ms: int) -> int:
    return int(candle.get("T", _candle_start(candle) + interval_ms - 1))


def _open(candle: dict[str, Any]) -> float | None:
    return _float_or_none(candle.get("o"))


def _close(candle: dict[str, Any]) -> float | None:
    return _float_or_none(candle.get("c"))


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_candle_at_or_after(candles: list[dict[str, Any]], target_ms: int) -> dict[str, Any] | None:
    candidates = [candle for candle in candles if _candle_start(candle) >= target_ms]
    if not candidates:
        return None
    return min(candidates, key=_candle_start)


def _first_candle_closing_at_or_after(
    candles: list[dict[str, Any]],
    target_ms: int,
    interval_ms: int,
) -> dict[str, Any] | None:
    candidates = [candle for candle in candles if _candle_close(candle, interval_ms) >= target_ms]
    if not candidates:
        return None
    return min(candidates, key=lambda candle: _candle_close(candle, interval_ms))


def _iso_utc(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze post-listing performance from Hyperliquid candles.")
    parser.add_argument("--config", default="config/settings.json", help="JSON config file path.")
    parser.add_argument("--symbols", help="Comma-separated symbols to analyze. Defaults to all current perps.")
    parser.add_argument("--universe", choices=("all", "core"), default="all", help="Use all perp dexes or core only.")
    parser.add_argument("--dex", help="Restrict to one perp dex name, for example xyz.")
    parser.add_argument("--category", choices=("all", "stocks"), default="all", help="Optional asset category filter.")
    parser.add_argument("--limit", type=int, help="Limit number of current perp symbols for a quick run.")
    parser.add_argument("--output-dir", default="reports", help="Directory for CSV/JSON reports.")
    parser.add_argument("--sleep", type=float, default=0.05, help="Seconds to sleep between symbols.")
    parser.add_argument("--resume", action="store_true", help="Skip symbols already present in listing_performance.json.")
    parser.add_argument("--retry-errors", action="store_true", help="With --resume, retry rows whose listing_confidence is error.")
    parser.add_argument(
        "--refresh-missing-volume",
        action="store_true",
        help="With --resume, refresh existing non-error rows that were generated before volume fields were added.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = Path(args.config)
    config = AgentConfig.from_env(config_path if config_path.exists() else None)
    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()] if args.symbols else None
    client = HyperliquidInfoClient(config.api_url, timeout_s=10)
    all_symbols = discover_perp_symbols(
        client,
        universe=args.universe,
        symbols=symbols,
        dex=args.dex,
        category=args.category,
    )
    if args.limit is not None:
        all_symbols = all_symbols[: args.limit]

    output_dir = Path(args.output_dir)
    existing = read_existing_report(output_dir / "listing_performance.json") if args.resume else []
    rows_by_symbol = {row.symbol: row for row in existing}
    report_symbols = list(dict.fromkeys([row.symbol for row in existing] + all_symbols)) if args.resume else all_symbols
    total = len(all_symbols)
    for index, symbol in enumerate(all_symbols, start=1):
        existing_row = rows_by_symbol.get(symbol)
        should_retry_error = args.retry_errors and existing_row is not None and existing_row.listing_confidence == "error"
        should_refresh_volume = (
            args.refresh_missing_volume
            and existing_row is not None
            and existing_row.listing_confidence != "error"
            and not _row_has_volume_fields(existing_row)
        )
        if existing_row is not None and not should_retry_error and not should_refresh_volume:
            print(f"[{index}/{total}] {symbol} skipped", flush=True)
            continue
        if should_retry_error:
            print(f"[{index}/{total}] {symbol} retrying previous error", flush=True)
        if should_refresh_volume:
            print(f"[{index}/{total}] {symbol} refreshing missing volume", flush=True)
        try:
            row = analyze_symbol(client, symbol)
            print(f"[{index}/{total}] {symbol} {row.listing_confidence}", flush=True)
        except Exception as exc:
            if existing_row is not None and existing_row.listing_confidence != "error":
                row = existing_row
                print(f"[{index}/{total}] {symbol} error kept existing row: {exc}", flush=True)
            else:
                row = _error_row(symbol, exc)
                print(f"[{index}/{total}] {symbol} error: {exc}", flush=True)
        rows_by_symbol[symbol] = row
        write_reports([rows_by_symbol[symbol] for symbol in report_symbols if symbol in rows_by_symbol], output_dir)
        if args.sleep > 0:
            time.sleep(args.sleep)

    rows = [rows_by_symbol[symbol] for symbol in report_symbols if symbol in rows_by_symbol]
    json_path, csv_path = write_reports(rows, output_dir)
    print(f"Wrote {len(rows)} assets")
    print(f"JSON: {json_path}")
    print(f"CSV: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
