# pyright: reportArgumentType=false
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from screen_airdrop.receiver.screen_live_runtime import (
    DecodeCompletion,
    FrameSlotDescriptor,
    ScreenLiveRuntime,
    ScreenLiveRuntimeStats,
)
from screen_airdrop.receiver.runtime.frame_preprocessor import (
    clip_roi_to_frame,
    compute_fingerprint,
)
from screen_airdrop.receiver.runtime.geometry_tracker import GeometryState
from screen_airdrop.receiver.runtime.slot_manager import SlotManager


def test_slot_registry_rejects_stale_descriptor_after_reuse() -> None:
    registry = SlotManager(["slot-a"])
    allocated = registry.allocate_for_grab("grab:1")
    assert allocated is not None
    slot_id, generation, _ = allocated
    descriptor = FrameSlotDescriptor(
        slot_id=slot_id,
        generation=generation,
        capture_index=1,
        ts=1.0,
        width=10,
        height=10,
        fingerprint=b"a",
    )
    assert registry.mark_filled(descriptor, "grab:1")
    assert registry.mark_duplicate_and_release(descriptor)

    allocated_again = registry.allocate_for_grab("grab:1")
    assert allocated_again is not None
    _, new_generation, _ = allocated_again
    assert new_generation != generation
    assert not registry.descriptor_matches_current(descriptor)
    assert registry.snapshot_generation_mismatch() >= 1


def test_slot_registry_holds_release_until_dump_reader_clears() -> None:
    registry = SlotManager(["slot-a"])
    allocated = registry.allocate_for_grab("grab:1")
    assert allocated is not None
    slot_id, generation, _ = allocated
    descriptor = FrameSlotDescriptor(
        slot_id=slot_id,
        generation=generation,
        capture_index=1,
        ts=1.0,
        width=10,
        height=10,
        fingerprint=b"a",
    )
    assert registry.mark_filled(descriptor, "grab:1")
    assert registry.set_dump_reader(descriptor)
    assert registry.assign_decode(descriptor, 0)  # Returns True now
    assert registry.complete_decode(descriptor, 0)
    assert registry.descriptor_matches_current(descriptor)
    assert registry.clear_dump_reader(descriptor)
    allocated_again = registry.allocate_for_grab("grab:1")
    assert allocated_again is not None
    assert allocated_again[0] == slot_id

def test_runtime_rejects_stale_geometry_update() -> None:
    from screen_airdrop.receiver.runtime.geometry_tracker import GeometryTracker

    tracker = GeometryTracker(
        locator_confidence_threshold=0.55,
        lock_fail_reacquire_threshold=5,
    )

    # Set up initial locked geometry at generation 3
    initial_geometry = GeometryState(
        stream_id="screen:0",
        geometry_generation=3,
        quad_src=None,
        homography=None,
        homography_inv=None,
        source_capture_index=10,
        last_success_frame_id=11,
        last_success_chunk_id=12,
        quality_score=0.9,
        lock_mode="locked",
    )
    tracker._geometry_state = initial_geometry
    tracker._geometry_generation = 3
    tracker._lock_mode = "locked"

    # Propose stale geometry (used_generation=2 < current_generation=3)
    proposed = GeometryState(
        stream_id="screen:0",
        geometry_generation=4,
        quad_src=None,
        homography=None,
        homography_inv=None,
        source_capture_index=20,
        last_success_frame_id=21,
        last_success_chunk_id=22,
        quality_score=0.95,
        lock_mode="locked",
    )

    # Attempt to update with stale geometry (should be rejected)
    tracker.propose_update(
        proposed_geometry=proposed,
        decode_quality=0.99,
        used_geometry_generation=2,  # Stale: 2 < 3
    )

    # Verify geometry was NOT updated (still at generation 3)
    assert tracker.current_generation == 3
    assert tracker.current_geometry is not None
    assert tracker.current_geometry.source_capture_index == 10


def test_clip_roi_to_frame_prefers_center_crop_when_none() -> None:
    roi = clip_roi_to_frame(None, frame_width=1000, frame_height=500)
    assert roi == (100, 50, 800, 400)


def test_fingerprint_uses_roi() -> None:
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[40:60, 40:60, :] = 255
    roi = (40, 40, 20, 20)
    fingerprint = compute_fingerprint(frame, roi)
    # Fingerprint should be mostly white since ROI is white
    fingerprint_arr = np.frombuffer(fingerprint, dtype=np.uint8).reshape(16, 24)
    assert int(fingerprint_arr.mean()) > 200  # Mostly white


def test_runtime_rejects_prep_process_gt_one() -> None:
    with pytest.raises(ValueError, match="prep_process must be 0 or 1"):
        ScreenLiveRuntime(
            capture=SimpleNamespace(monitor_index=1, window_title=None, region=None, active_region=None),
            assembler=SimpleNamespace(),
            prep_process=2,
        )


def test_stats_snapshot_reports_async_prep_mode() -> None:
    stats = ScreenLiveRuntimeStats(protocol="layered", prep_mode="async", prep_processes=0)
    snap = stats.snapshot()
    assert snap["pipeline_prep_mode"] == "async"
    assert snap["pipeline_prep_processes"] == 0


def test_stats_snapshot_reports_process_prep_mode() -> None:
    stats = ScreenLiveRuntimeStats(protocol="layered", prep_mode="process", prep_processes=1)
    snap = stats.snapshot()
    assert snap["pipeline_prep_mode"] == "process"
    assert snap["pipeline_prep_processes"] == 1
