import csv
import tempfile
import unittest
from pathlib import Path

from listing_agent.listing_analysis import (
    ListingPerformance,
    build_summary,
    discover_perp_symbols,
    _first_candle_at_or_after,
    _first_candle_closing_at_or_after,
    _iso_utc,
    _window_results,
    write_reports,
)


class ListingAnalysisTests(unittest.TestCase):
    def test_first_candle_at_or_after(self):
        candles = [{"t": 1000, "c": "1"}, {"t": 2000, "c": "2"}, {"t": 3000, "c": "3"}]

        self.assertEqual(_first_candle_at_or_after(candles, 1500)["t"], 2000)
        self.assertIsNone(_first_candle_at_or_after(candles, 4000))

    def test_iso_utc(self):
        self.assertEqual(_iso_utc(0), "1970-01-01T00:00:00+00:00")

    def test_window_results(self):
        class FakeClient:
            calls = []

            def candles(self, coin, interval, start_time_ms, end_time_ms):
                self.calls.append((coin, interval, start_time_ms, end_time_ms))
                if interval not in {"1m", "5m"}:
                    return ([], 1.0)
                return (
                    [
                        {"t": 0, "T": 60_000, "c": "110", "v": "10", "n": 2},
                        {"t": 300_000, "T": 600_000, "c": "120", "v": "20", "n": 3},
                    ],
                    1.0,
                )

        results = _window_results(FakeClient(), "TEST", 0, 100, 700_000)

        self.assertEqual(results["1m"]["return_pct"], 10.0)
        self.assertEqual(results["5m"]["return_pct"], 20.0)
        self.assertEqual(results["5m"]["volume"], 20.0)
        self.assertEqual(results["5m"]["trade_count"], 3)
        self.assertEqual(results["15m"]["status"], "missing")
        self.assertEqual(FakeClient.calls[0][1], "1m")
        self.assertEqual(FakeClient.calls[1][1], "3m")
        self.assertEqual(FakeClient.calls[2][1], "5m")

    def test_window_results_falls_back_to_daily_for_one_day(self):
        class FakeClient:
            def candles(self, coin, interval, start_time_ms, end_time_ms):
                return ([], 1.0)

        results = _window_results(
            FakeClient(),
            "TEST",
            0,
            100,
            2 * 86_400_000,
            daily_candles=[{"t": 86_400_000, "c": "130"}],
        )

        self.assertEqual(results["1d"]["return_pct"], 30.0)
        self.assertEqual(results["1d"]["source_interval"], "1d")

    def test_window_results_does_not_calculate_late_window(self):
        class FakeClient:
            def candles(self, coin, interval, start_time_ms, end_time_ms):
                if interval == "1m":
                    return ([{"t": 180_000, "T": 240_000, "c": "150", "v": "99", "n": 9}], 1.0)
                return ([], 1.0)

        results = _window_results(FakeClient(), "TEST", 0, 100, 700_000)

        self.assertEqual(results["1m"]["status"], "late")
        self.assertIsNone(results["1m"]["price"])
        self.assertIsNone(results["1m"]["return_pct"])
        self.assertIsNone(results["1m"]["volume"])
        self.assertIsNone(results["1m"]["trade_count"])

    def test_write_reports_splits_performance_and_quality_tables(self):
        row = ListingPerformance(
            "TEST",
            0,
            "1970-01-01T00:00:00+00:00",
            "1m_candleSnapshot",
            "observed",
            100.0,
            {
                "1m": {
                    "price": 110.0,
                    "return_pct": 10.12,
                    "volume": 50.0,
                    "trade_count": 5,
                    "status": "ok",
                    "source_interval": "1m",
                    "time_utc": "1970-01-01T00:01:00+00:00",
                },
                "3m": {
                    "price": None,
                    "return_pct": None,
                    "volume": None,
                    "trade_count": None,
                    "status": "late",
                    "source_interval": "3m",
                    "time_utc": "1970-01-01T00:09:00+00:00",
                },
            },
            "sample note",
        )
        with tempfile.TemporaryDirectory() as tmp:
            write_reports([row], Path(tmp))
            with (Path(tmp) / "listing_performance.csv").open(encoding="utf-8", newline="") as handle:
                performance = next(csv.DictReader(handle))
            with (Path(tmp) / "data_quality.csv").open(encoding="utf-8", newline="") as handle:
                quality = next(csv.DictReader(handle))

        self.assertIn("1m_return_pct", performance)
        self.assertIn("1m_volume", performance)
        self.assertNotIn("listing_source", performance)
        self.assertNotIn("1m_status", performance)
        self.assertEqual(performance["1m_return_pct"], "10.12")
        self.assertEqual(performance["3m_return_pct"], "")
        self.assertEqual(quality["listing_source"], "1m_candleSnapshot")
        self.assertEqual(quality["3m_status"], "late")
        self.assertEqual(quality["3m_source_interval"], "3m")

    def test_first_candle_closing_at_or_after(self):
        candles = [{"t": 0, "T": 59_999}, {"t": 60_000, "T": 119_999}]

        self.assertEqual(_first_candle_closing_at_or_after(candles, 60_000, 60_000)["t"], 60_000)

    def test_discover_perp_symbols_matches_suffix(self):
        class FakeClient:
            def post(self, payload):
                if payload["type"] == "allPerpMetas":
                    return (
                        [
                            {"universe": [{"name": "BTC"}]},
                            {"universe": [{"name": "xyz:CBRS"}, {"name": "xyz:AAPL"}]},
                        ],
                        1.0,
                    )
                return ([None, {"name": "xyz"}], 1.0)

        symbols = discover_perp_symbols(FakeClient(), universe="all", symbols=["CBRS"])

        self.assertEqual(symbols, ["xyz:CBRS"])

    def test_discover_perp_symbols_filters_dex_and_stocks(self):
        class FakeClient:
            def post(self, payload):
                if payload["type"] == "allPerpMetas":
                    return (
                        [
                            {"universe": [{"name": "BTC"}]},
                            {"universe": [{"name": "xyz:CBRS"}, {"name": "xyz:GOLD"}]},
                        ],
                        1.0,
                    )
                return ([None, {"name": "xyz"}], 1.0)

        symbols = discover_perp_symbols(FakeClient(), universe="all", dex="xyz", category="stocks")

        self.assertEqual(symbols, ["xyz:CBRS"])

    def test_build_summary(self):
        rows = [
            ListingPerformance("A", 0, "", "", "", 1.0, {"1m": {"return_pct": 10.0, "volume": 100.0}}, ""),
            ListingPerformance("B", 0, "", "", "", 1.0, {"1m": {"return_pct": -5.0, "volume": 300.0}}, ""),
            ListingPerformance("C", 0, "", "", "", 1.0, {"1m": {"return_pct": None, "volume": None}}, ""),
        ]

        summary = build_summary(rows)
        one_minute = next(row for row in summary if row["window"] == "1m")

        self.assertEqual(one_minute["asset_count"], 3)
        self.assertEqual(one_minute["valid_count"], 2)
        self.assertEqual(one_minute["missing_count"], 1)
        self.assertEqual(one_minute["win_rate_pct"], 50.0)
        self.assertEqual(one_minute["volume_valid_count"], 2)
        self.assertEqual(one_minute["volume_missing_count"], 1)
        self.assertEqual(one_minute["mean_volume"], 200.0)
        self.assertEqual(one_minute["median_volume"], 200.0)
        self.assertEqual(one_minute["total_volume"], 400.0)


if __name__ == "__main__":
    unittest.main()
