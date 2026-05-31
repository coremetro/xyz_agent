from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from ..config import AgentConfig
from .alert_service import WebhookAlertService
from .all_mids_watcher import AllMidsWatcher
from .client import AsyncHyperliquidInfoClient
from .metadata_watcher import MetadataWatcher
from .storage import JsonMonitorStore
from .verifier import AssetVerifier


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monitor trade.xyz / XYZ new asset signals.")
    parser.add_argument("--config", default="config/settings.json", help="JSON config file path.")
    parser.add_argument("--dex", default="xyz", help="Perp dex name. Defaults to xyz.")
    parser.add_argument("--state-dir", default="state/monitor", help="Directory for monitor JSON/JSONL state.")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Metadata poll interval in seconds.")
    parser.add_argument("--once", action="store_true", help="Run one metadata poll and exit.")
    parser.add_argument("--init-baseline", action="store_true", help="Record current assets without alerts and exit.")
    parser.add_argument("--verify", help="Verify one ticker and exit, for example xyz:BB.")
    parser.add_argument("--webhook-url", default="", help="Optional generic webhook URL for alerts.")
    parser.add_argument("--with-ws", action="store_true", help="Also listen to WebSocket allMids new keys.")
    parser.add_argument("--ws-url", default="wss://api.hyperliquid.xyz/ws", help="Hyperliquid WebSocket URL.")
    return parser


async def async_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = Path(args.config)
    config = AgentConfig.from_env(config_path if config_path.exists() else None)
    client = AsyncHyperliquidInfoClient(config.api_url, timeout_s=10)
    store = JsonMonitorStore(Path(args.state_dir))
    watcher = MetadataWatcher(client, store, dex=args.dex)
    verifier = AssetVerifier(client, store, dex=args.dex)
    alerts = WebhookAlertService(store, webhook_url=args.webhook_url)

    if args.verify:
        result = await verifier.verify(args.verify.upper())
        alerts.send_if_needed(result)
        print(f"{result.ticker} state={result.state} score={result.score} action={result.recommended_action}")
        return 0

    async def verify_and_alert(ticker: str, metadata: dict | None = None) -> None:
        result = await verifier.verify(ticker, metadata=metadata)
        alerts.send_if_needed(result)
        print(f"NEW {ticker} state={result.state} score={result.score} action={result.recommended_action}")

    ws_task: asyncio.Task[None] | None = None
    if args.with_ws and not args.once and not args.init_baseline:
        async def on_ws_event(event):
            await verify_and_alert(event.ticker, metadata=event.payload)

        ws_task = asyncio.create_task(AllMidsWatcher(args.ws_url, store, dex=args.dex, on_event=on_ws_event).run())

    while True:
        events = await watcher.run_once(init_baseline=args.init_baseline)
        if args.init_baseline:
            if ws_task is not None:
                ws_task.cancel()
            print(f"Initialized {args.dex} monitor baseline at {args.state_dir}")
            return 0
        for event in events:
            await verify_and_alert(event.ticker, metadata=event.payload)
        if args.once:
            if ws_task is not None:
                ws_task.cancel()
            print(f"Checked {args.dex}; new_assets={len(events)}")
            return 0
        await asyncio.sleep(args.poll_interval)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
