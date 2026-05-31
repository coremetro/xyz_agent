from __future__ import annotations

import time


def now_ms() -> int:
    return int(time.time() * 1000)


def monotonic_ms() -> float:
    return time.monotonic() * 1000
