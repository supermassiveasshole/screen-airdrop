"""Debug utilities for screen-airdrop receiver."""

from screen_airdrop.receiver.debug.drawing import FrameDrawer
from screen_airdrop.receiver.debug.metadata import DebugMetadataBuilder
from screen_airdrop.receiver.debug.probes import probe_compact_debug, probe_locator_debug
from screen_airdrop.receiver.debug.snapshot import DebugSnapshotManager

__all__ = [
    "FrameDrawer",
    "DebugMetadataBuilder",
    "DebugSnapshotManager",
    "probe_locator_debug",
    "probe_compact_debug",
]
