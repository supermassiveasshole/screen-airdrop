"""Tests for grab statistics separation (raw_grab vs captured)."""


from screen_airdrop.receiver.runtime.events import FilledSlotEvent, FrameSlotDescriptor
from screen_airdrop.receiver.runtime.stats import ScreenLiveRuntimeStats


def test_raw_grab_stats_separate_from_captured():
    """Test that raw_grab_frames and captured are tracked separately."""
    stats = ScreenLiveRuntimeStats(protocol="layered")

    # Simulate raw grab stats (before slot assignment)
    with stats._lock:
        stats.raw_grab_frames += 1
        stats.capture_grab_time_ms += 20.0
        stats.capture_grab_ops += 1

    # Simulate captured (after successful slot assignment)
    with stats._lock:
        stats.captured += 1
        stats.capture_copy_time_ms += 5.0
        stats.capture_copy_ops += 1

    # Verify separation
    assert stats.raw_grab_frames == 1
    assert stats.captured == 1
    assert stats.capture_grab_ops == 1
    assert stats.capture_copy_ops == 1


def test_raw_grab_higher_than_captured_when_slots_full():
    """Test that raw_grab_frames can exceed captured when slots are full."""
    stats = ScreenLiveRuntimeStats(protocol="layered")

    # Simulate 10 grabs
    for _ in range(10):
        with stats._lock:
            stats.raw_grab_frames += 1
            stats.capture_grab_time_ms += 20.0
            stats.capture_grab_ops += 1

    # But only 7 got slots
    for _ in range(7):
        with stats._lock:
            stats.captured += 1
            stats.capture_copy_time_ms += 5.0
            stats.capture_copy_ops += 1

    # Verify
    assert stats.raw_grab_frames == 10
    assert stats.captured == 7
    assert stats.capture_grab_ops == 10
    assert stats.capture_copy_ops == 7


def test_copy_ms_calculation():
    """Test that copy_ms is correctly calculated from stats."""
    stats = ScreenLiveRuntimeStats(protocol="layered")

    # Simulate multiple copies
    with stats._lock:
        stats.capture_copy_time_ms = 50.0  # 5 copies * 10ms each
        stats.capture_copy_ops = 5

    snapshot = stats.snapshot()

    # Verify copy stats are in snapshot
    assert snapshot["capture_copy_time_ms"] == 50.0
    assert snapshot["capture_copy_ops"] == 5


def test_filled_slot_event_has_copy_ms():
    """Test that FilledSlotEvent includes copy_ms field."""
    descriptor = FrameSlotDescriptor(
        slot_id=0,
        generation=1,
        capture_index=0,
        ts=0.0,
        width=1920,
        height=1080,
        fingerprint=b"",
    )

    event = FilledSlotEvent(
        descriptor=descriptor,
        grab_ms=20.5,
        copy_ms=5.3,
    )

    assert event.grab_ms == 20.5
    assert event.copy_ms == 5.3


def test_snapshot_includes_all_grab_metrics():
    """Test that snapshot includes both raw_grab and captured metrics."""
    stats = ScreenLiveRuntimeStats(protocol="layered")

    with stats._lock:
        stats.raw_grab_frames = 100
        stats.captured = 95
        stats.capture_grab_time_ms = 2000.0
        stats.capture_grab_ops = 100
        stats.capture_copy_time_ms = 475.0
        stats.capture_copy_ops = 95

    snapshot = stats.snapshot()

    assert snapshot["raw_grab_frames"] == 100
    assert snapshot["captured"] == 95
    assert snapshot["capture_grab_time_ms"] == 2000.0
    assert snapshot["capture_grab_ops"] == 100
    assert snapshot["capture_copy_time_ms"] == 475.0
    assert snapshot["capture_copy_ops"] == 95
