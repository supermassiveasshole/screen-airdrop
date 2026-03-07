"""Runtime compatibility helpers for sender CLIs."""

from __future__ import annotations

import sys
import time


def require_python(min_major: int, min_minor: int) -> None:
    current = sys.version_info
    if (current.major, current.minor) < (min_major, min_minor):
        raise RuntimeError(
            "Python {0}.{1}+ required, current: {2}.{3}".format(
                min_major, min_minor, current.major, current.minor
            )
        )


def now_ms() -> int:
    return int(time.time() * 1000)
