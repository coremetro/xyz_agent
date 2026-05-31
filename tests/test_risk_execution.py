import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from listing_agent.audit import AuditLogger
from listing_agent.config import AgentConfig
from listing_agent.execution import (
    ExecutionAdapter,
    _cloid_from_key,
    _open_position,
    _size_at_or_below_notional,
    _size_for_notional,
)
from listing_agent.main import run_live_buy, run_live_close, run_live_preflight, run_simulated_order
from listing_agent.models import Asset, Candidate, MarketCheck
from listing_agent.risk import RiskEngine


def _candidate() -> Candidate:
    return Candidate(
        asset=Asset("perp", "99", "NEW", {"name": "NEW"}),
        discovered_at_ms=123,
        reason="test",
    )


class RiskExecutionTests(unittest.TestCase):
    def test_risk_engine_creates_dry_run_intent(self):
        config = AgentConfig(dry_run=True, max_notional_usd=10, max_total_exposure_usd=20)
        intent = RiskEngine(config).create_buy_intent(_candidate(), MarketCheck(True, "ok", {}))

        self.assertTrue(intent.dry_run)
        self.assertEqual(intent.notional_usd, 10)
        self.assertEqual(intent.idempotency_key, "buy:perp:99:123")

    def test_risk_engine_allows_smaller_requested_notional(self):
        config = AgentConfig(dry_run=True, max_notional_usd=10, max_total_exposure_usd=20)
        intent = RiskEngine(config).create_buy_intent(_candidate(), MarketCheck(True, "ok", {}), 5)

        self.assertEqual(intent.notional_usd, 5)

    def test_risk_engine_rejects_notional_above_config_limit(self):
        config = AgentConfig(dry_run=True, max_notional_usd=10, max_total_exposure_usd=20)

        with self.assertRaisesRegex(ValueError, "MAX_NOTIONAL_USD"):
            RiskEngine(config).create_buy_intent(_candidate(), MarketCheck(True, "ok", {}), 11)

    def test_risk_engine_suppresses_duplicate_intents(self):
        engine = RiskEngine(AgentConfig())
        candidate = _candidate()
        engine.create_buy_intent(candidate, MarketCheck(True, "ok", {}))

        with self.assertRaisesRegex(ValueError, "duplicate"):
            engine.create_buy_intent(candidate, MarketCheck(True, "ok", {}))

    def test_execution_adapter_refuses_live_execution(self):
        config = AgentConfig(dry_run=True)
        intent = RiskEngine(config).create_buy_intent(_candidate(), MarketCheck(True, "ok", {}))
        live_intent = type(intent)(
            idempotency_key=intent.idempotency_key,
            asset_key=intent.asset_key,
            symbol=intent.symbol,
            side=intent.side,
            notional_usd=intent.notional_usd,
            order_type=intent.order_type,
            dry_run=False,
            reason=intent.reason,
        )

        with self.assertRaisesRegex(RuntimeError, "Live execution"):
            ExecutionAdapter().submit(live_intent)

    def test_simulated_order_writes_dry_run_audit_log(self):
        with TemporaryDirectory() as tmpdir:
            audit_path = Path(tmpdir) / "audit.jsonl"
            config = AgentConfig(dry_run=True, audit_log_path=audit_path)
            with redirect_stdout(StringIO()):
                code = run_simulated_order("TEST", "perp", "123", config, AuditLogger(audit_path))

            self.assertEqual(code, 0)
            content = audit_path.read_text(encoding="utf-8")
            self.assertIn("order_intent_created", content)
            self.assertIn("perp:123", content)

    def test_simulated_order_refuses_live_mode(self):
        with TemporaryDirectory() as tmpdir:
            audit_path = Path(tmpdir) / "audit.jsonl"
            config = AgentConfig(dry_run=False, audit_log_path=audit_path)

            with self.assertRaisesRegex(ValueError, "DRY_RUN=true"):
                run_simulated_order("TEST", "perp", "123", config, AuditLogger(audit_path))

    def test_live_buy_requires_explicit_flag_before_sdk_import(self):
        with TemporaryDirectory() as tmpdir:
            audit_path = Path(tmpdir) / "audit.jsonl"
            config = AgentConfig(
                dry_run=False,
                audit_log_path=audit_path,
                live_trading_ack="I_UNDERSTAND_THIS_PLACES_REAL_ORDERS",
                account_address="0x0000000000000000000000000000000000000000",
                secret_key="0x" + "1" * 64,
            )

            with self.assertRaisesRegex(ValueError, "--i-understand-live-order"):
                run_live_buy("BTC", False, config, AuditLogger(audit_path))

    def test_live_preflight_requires_live_mode(self):
        with TemporaryDirectory() as tmpdir:
            audit_path = Path(tmpdir) / "audit.jsonl"
            config = AgentConfig(dry_run=True, audit_log_path=audit_path)

            with self.assertRaisesRegex(ValueError, "DRY_RUN=false"):
                run_live_preflight("BTC", config, AuditLogger(audit_path))

    def test_live_close_requires_confirmation_before_sdk_import(self):
        with TemporaryDirectory() as tmpdir:
            audit_path = Path(tmpdir) / "audit.jsonl"
            config = AgentConfig(
                dry_run=False,
                audit_log_path=audit_path,
                live_trading_ack="I_UNDERSTAND_THIS_PLACES_REAL_ORDERS",
                account_address="0x0000000000000000000000000000000000000000",
                secret_key="0x" + "1" * 64,
            )

            with self.assertRaisesRegex(ValueError, "--yes"):
                run_live_close("BTC", False, config, AuditLogger(audit_path))

    def test_live_config_refuses_active_stop_file(self):
        with TemporaryDirectory() as tmpdir:
            stop_file = Path(tmpdir) / "STOP"
            stop_file.write_text("stop", encoding="utf-8")
            config = AgentConfig(
                dry_run=False,
                stop_file_path=stop_file,
                live_trading_ack="I_UNDERSTAND_THIS_PLACES_REAL_ORDERS",
                account_address="0x0000000000000000000000000000000000000000",
                secret_key="0x" + "1" * 64,
            )

            with self.assertRaisesRegex(ValueError, "Kill switch"):
                config.validate()

    def test_cloid_is_128_bit_hex(self):
        cloid = _cloid_from_key("buy:perp:BTC:123")

        self.assertRegex(cloid, r"^0x[0-9a-f]{32}$")

    def test_size_for_notional_rounds_up_to_size_decimals(self):
        size = _size_for_notional(10, 74731.0, 5)

        self.assertEqual(size, 0.00014)

    def test_size_at_or_below_notional_rounds_down_to_size_decimals(self):
        size = _size_at_or_below_notional(10, 74731.0, 5)

        self.assertEqual(size, 0.00013)

    def test_size_at_or_below_notional_can_fit_btc_twelve_usd(self):
        size = _size_at_or_below_notional(12, 74731.0, 5)

        self.assertEqual(size, 0.00016)
        self.assertLessEqual(size * 74731.0, 12)
        self.assertGreaterEqual(size * 74731.0, 10)

    def test_open_position_finds_non_zero_position(self):
        class FakeInfo:
            def user_state(self, account_address):
                return {
                    "assetPositions": [
                        {"position": {"coin": "ETH", "szi": "0"}},
                        {"position": {"coin": "BTC", "szi": "0.00016", "time": 123}},
                    ]
                }

        position = _open_position(FakeInfo(), "0xabc", "BTC")

        self.assertEqual(position["szi"], "0.00016")

    def test_config_file_loads_risk_settings_without_env(self):
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "settings.json"
            config_path.write_text(
                """
                {
                  "dry_run": true,
                  "markets": "perp",
                  "max_notional_usd": 5,
                  "max_total_exposure_usd": 10,
                  "max_daily_loss_usd": 5,
                  "slippage_bps": 50,
                  "asset_allowlist": ["BTC", "ETH"]
                }
                """,
                encoding="utf-8",
            )

            config = AgentConfig.from_env(config_path)

            self.assertTrue(config.dry_run)
            self.assertEqual(config.markets, ("perp",))
            self.assertEqual(config.max_notional_usd, 5)
            self.assertEqual(config.max_total_exposure_usd, 10)
            self.assertEqual(config.max_daily_loss_usd, 5)
            self.assertEqual(config.slippage_bps, 50)
            self.assertEqual(config.allowlist, {"BTC", "ETH"})


if __name__ == "__main__":
    unittest.main()
