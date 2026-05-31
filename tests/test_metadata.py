import unittest

from listing_agent.metadata import diff_new_assets, parse_perp_assets, parse_spot_assets
from listing_agent.models import Snapshot


class MetadataTests(unittest.TestCase):
    def test_parse_perp_assets_uses_stable_index_keys(self):
        assets = parse_perp_assets({"universe": [{"name": "BTC"}, {"name": "NEW"}]})

        self.assertEqual(sorted(assets), ["perp:0", "perp:1"])
        self.assertEqual(assets["perp:1"].symbol, "NEW")

    def test_parse_spot_assets_builds_pair_symbol(self):
        meta = {
            "tokens": [{"index": 0, "name": "PURR"}, {"index": 1, "name": "USDC"}],
            "universe": [{"index": 7, "tokens": [0, 1]}],
        }

        assets = parse_spot_assets(meta)

        self.assertEqual(sorted(assets), ["spot:7"])
        self.assertEqual(assets["spot:7"].symbol, "PURR/USDC")

    def test_diff_new_assets_detects_only_absent_keys(self):
        assets = parse_perp_assets({"universe": [{"name": "BTC"}, {"name": "NEW"}]})
        snapshot = Snapshot(assets=assets, fetched_at_ms=123, latency_ms=1.5, raw_hash="abc")

        candidates = diff_new_assets({"perp:0"}, snapshot)

        self.assertEqual([candidate.asset.key for candidate in candidates], ["perp:1"])
        self.assertEqual(candidates[0].reason, "asset key was absent from baseline")


if __name__ == "__main__":
    unittest.main()
