"""Receiver package organized by stable subdomains.

The receiver is structured around:

1. ``cli``: user-facing entrypoints
2. ``application``: high-level orchestration and restore wiring
3. ``roi``: region-selection policy and transforms
4. ``locator``: pluggable geometry/location services
5. ``transport``: protocol-specific single-frame decode
6. ``information``: semantic assembly and future generation state
7. ``pipeline``: pluggable decode pipeline implementations
8. ``runtime``: shared infrastructure used by pipelines
9. ``reporting``: collectors, formatters, and reporter backends

These subpackages are the supported receiver implementation surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.receiver import (
        application,
        information,
        locator,
        pipeline,
        reporting,
        roi,
        runtime,
        transport,
    )

__all__ = [
    "application",
    "information",
    "locator",
    "pipeline",
    "reporting",
    "roi",
    "runtime",
    "transport",
]


def __getattr__(name):
    if name in __all__:
        import importlib

        return importlib.import_module("screen_airdrop.receiver." + name)
    raise AttributeError(name)
