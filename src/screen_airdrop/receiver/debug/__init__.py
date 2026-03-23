"""Narrow debug facade for explicit debug entrypoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.receiver.debug.probes import probe_compact_debug, probe_locator_debug
    from screen_airdrop.receiver.debug.snapshot import DebugSnapshotManager

__all__ = [
    "DebugSnapshotManager",
    "probe_locator_debug",
    "probe_compact_debug",
]


def __getattr__(name):
    if name in {"probe_locator_debug", "probe_compact_debug"}:
        from screen_airdrop.receiver.debug import probes as _probes

        return getattr(_probes, name)
    if name == "DebugSnapshotManager":
        from screen_airdrop.receiver.debug.snapshot import DebugSnapshotManager

        return DebugSnapshotManager
    raise AttributeError(name)
