from __future__ import annotations

import argparse
from collections.abc import Callable

from . import listing_analysis
from . import main as trading_main
from .monitor import runner as monitor_runner


Command = Callable[[list[str] | None], int]


COMMANDS: dict[str, tuple[str, Command]] = {
    "analyze": ("Analyze historical listing performance.", listing_analysis.main),
    "monitor": ("Monitor XYZ for newly listed assets.", monitor_runner.main),
    "trade": ("Run trading, preflight, buy, close, and dry-run order commands.", trading_main.main),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trade-xyz",
        description="Unified entrypoint for analysis, monitoring, and trading workflows.",
    )
    parser.add_argument("module", nargs="?", choices=sorted(COMMANDS), help="Workflow module to run.")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed to the selected module.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parsed = parser.parse_args(argv)
    if parsed.module is None:
        parser.print_help()
        return 0
    _, command = COMMANDS[parsed.module]
    return command(parsed.args)


if __name__ == "__main__":
    raise SystemExit(main())

