import asyncio
import tempfile
import unittest
from pathlib import Path

from listing_agent.monitor.all_mids_watcher import AllMidsWatcher, extract_mids
from listing_agent.monitor.metadata_watcher import MetadataWatcher, extract_dex_assets
from listing_agent.monitor.models import BOOK_DETECTED, METADATA_DETECTED, AssetSnapshot
from listing_agent.monitor.scoring import score_asset
from listing_agent.monitor.state_machine import infer_state
from listing_agent.monitor.storage import JsonMonitorStore
from listing_agent.monitor.verifier import AssetVerifier


class MonitorTests(unittest.TestCase):
    def test_extract_dex_assets(self):
        assets = extract_dex_assets(
            [{"universe": [{"name": "BTC"}]}, {"universe": [{"name": "xyz:BB"}]}],
            [None, {"name": "xyz"}],
            "xyz",
        )

        self.assertEqual(sorted(assets), ["XYZ:BB"])

    def test_metadata_watcher_initializes_baseline_without_events(self):
        class FakeClient:
            async def all_perp_metas(self):
                return [{"universe": [{"name": "BTC"}]}, {"universe": [{"name": "xyz:BB"}]}]

            async def perp_dexs(self):
                return [None, {"name": "xyz"}]

        with tempfile.TemporaryDirectory() as tmp:
            store = JsonMonitorStore(Path(tmp))
            watcher = MetadataWatcher(FakeClient(), store, dex="xyz")
            events = asyncio.run(watcher.run_once())

            self.assertEqual(events, [])
            self.assertEqual(store.known_tickers("xyz"), {"XYZ:BB"})

    def test_metadata_watcher_detects_new_asset_after_baseline(self):
        class FakeClient:
            calls = 0

            async def all_perp_metas(self):
                self.calls += 1
                universe = [{"name": "xyz:BB"}]
                if self.calls > 1:
                    universe.append({"name": "xyz:QNT"})
                return [{"universe": [{"name": "BTC"}]}, {"universe": universe}]

            async def perp_dexs(self):
                return [None, {"name": "xyz"}]

        with tempfile.TemporaryDirectory() as tmp:
            store = JsonMonitorStore(Path(tmp))
            watcher = MetadataWatcher(FakeClient(), store, dex="xyz")
            asyncio.run(watcher.run_once())
            events = asyncio.run(watcher.run_once())

            self.assertEqual([event.event_type for event in events], ["NEW_METADATA_ASSET"])
            self.assertEqual(events[0].ticker, "XYZ:QNT")

    def test_state_and_scoring(self):
        snapshot = AssetSnapshot(
            dex="xyz",
            ticker="xyz:TEST",
            snapshot_time_ms=1,
            mid_px=100.0,
            best_bid=99.0,
            best_ask=101.0,
            spread_bps=200.0,
            book_depth_usd=5_000.0,
        )

        self.assertEqual(infer_state(snapshot), BOOK_DETECTED)
        score, action, reasons = score_asset(snapshot, {}, trade_count=0)

        self.assertEqual(score, 50)
        self.assertEqual(action, "PASSIVE_WATCH")
        self.assertTrue(reasons)

    def test_scoring_without_book_remains_metadata_level(self):
        snapshot = AssetSnapshot(dex="xyz", ticker="xyz:TEST", snapshot_time_ms=1)

        self.assertEqual(infer_state(snapshot), METADATA_DETECTED)
        score, action, _ = score_asset(snapshot, {}, trade_count=0)

        self.assertLess(score, 40)
        self.assertEqual(action, "IGNORE_OR_LOG_ONLY")

    def test_all_mids_watcher_message_diff(self):
        message = {"channel": "allMids", "data": {"mids": {"xyz:BB": "8.1"}}}

        with tempfile.TemporaryDirectory() as tmp:
            store = JsonMonitorStore(Path(tmp))
            watcher = AllMidsWatcher("ws://example.invalid", store, dex="xyz")
            events = watcher.handle_message(__import__("json").dumps(message))

            self.assertEqual(extract_mids(message), {"XYZ:BB": "8.1"})
            self.assertEqual([event.event_type for event in events], ["NEW_MID_KEY"])
            self.assertEqual(store.known_tickers("xyz"), {"XYZ:BB"})

    def test_verifier_uses_context_mid_price(self):
        class FakeClient:
            async def all_mids(self, dex):
                return {}

            async def meta_and_asset_ctxs(self, dex):
                return [
                    {"universe": [{"name": "XYZ:BB"}]},
                    [{"midPx": "8.2", "markPx": "8.21", "oraclePx": "8.20", "openInterest": "100"}],
                ]

            async def l2_book(self, ticker):
                return {}

            async def recent_trades(self, ticker):
                return []

        with tempfile.TemporaryDirectory() as tmp:
            verifier = AssetVerifier(FakeClient(), JsonMonitorStore(Path(tmp)), dex="xyz")
            result = asyncio.run(verifier.verify("XYZ:BB"))

            self.assertEqual(result.snapshot.mid_px, 8.2)
            self.assertEqual(result.state, "MID_DETECTED")


if __name__ == "__main__":
    unittest.main()
