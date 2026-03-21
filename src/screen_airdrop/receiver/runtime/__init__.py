"""Runtime components for screen live capture pipeline."""

from screen_airdrop.receiver.runtime.frame_preprocessor import (
    clip_roi_to_frame,
    compute_fingerprint,
    fingerprint_diff,
    is_duplicate,
)
from screen_airdrop.receiver.runtime.geometry_tracker import (
    GeometryState,
    GeometryTracker,
)
from screen_airdrop.receiver.runtime.prep_strategy import (
    AsyncPrepStrategy,
    PrepStrategy,
    ProcessPrepStrategy,
)
from screen_airdrop.receiver.runtime.slot_manager import SlotManager, SlotState
from screen_airdrop.receiver.runtime.stats import ScreenLiveRuntimeStats
from screen_airdrop.receiver.runtime.workers import (
    _attach_shared_memory_for_child,
    decode_worker_main,
    dump_worker_main,
    grab_process_main,
    prep_process_main,
)

__all__ = [
    "SlotManager",
    "SlotState",
    "GeometryState",
    "GeometryTracker",
    "ScreenLiveRuntimeStats",
    "PrepStrategy",
    "AsyncPrepStrategy",
    "ProcessPrepStrategy",
    "clip_roi_to_frame",
    "compute_fingerprint",
    "fingerprint_diff",
    "is_duplicate",
    "_attach_shared_memory_for_child",
    "grab_process_main",
    "decode_worker_main",
    "dump_worker_main",
    "prep_process_main",
]
