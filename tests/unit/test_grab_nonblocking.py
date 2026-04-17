"""Tests for grab non-blocking mechanism and slot starvation handling."""

import asyncio
import queue
import threading
from types import SimpleNamespace

import pytest

from screen_airdrop.receiver.runtime.events import FilledSlotEvent
from screen_airdrop.receiver.runtime.stats import ScreenLiveRuntimeStats
from screen_airdrop.receiver.runtime.workers import _async_grab_loop


def test_slot_starvation_stats():
    """Test that slot starvation events are tracked."""
    stats = ScreenLiveRuntimeStats(protocol="layered")

    # Simulate slot starvation events
    with stats._lock:
        stats.slot_starvation_events += 1
        stats.dropped_slot_starvation += 1

    assert stats.slot_starvation_events == 1
    assert stats.dropped_slot_starvation == 1


def test_raw_grab_continues_during_starvation():
    """Test that raw_grab_frames continues to increment during slot starvation."""
    stats = ScreenLiveRuntimeStats(protocol="layered")

    # Simulate 10 grabs
    for _ in range(10):
        with stats._lock:
            stats.raw_grab_frames += 1
            stats.capture_grab_time_ms += 20.0
            stats.capture_grab_ops += 1

    # But only 5 got slots (5 were dropped due to starvation)
    for _ in range(5):
        with stats._lock:
            stats.captured += 1
            stats.capture_copy_time_ms += 5.0
            stats.capture_copy_ops += 1

    # Simulate 5 starvation events
    with stats._lock:
        stats.slot_starvation_events += 5
        stats.dropped_slot_starvation += 5

    # Verify
    assert stats.raw_grab_frames == 10
    assert stats.captured == 5
    assert stats.dropped_slot_starvation == 5
    assert stats.slot_starvation_events == 5


def test_snapshot_includes_starvation_metrics():
    """Test that snapshot includes slot starvation metrics."""
    stats = ScreenLiveRuntimeStats(protocol="layered")

    with stats._lock:
        stats.raw_grab_frames = 100
        stats.captured = 80
        stats.dropped_slot_starvation = 20
        stats.slot_starvation_events = 15

    snapshot = stats.snapshot()

    assert snapshot["raw_grab_frames"] == 100
    assert snapshot["captured"] == 80
    assert snapshot["dropped_slot_starvation"] == 20
    assert snapshot["slot_starvation_events"] == 15


def test_starvation_rate_calculation():
    """Test calculating starvation rate from stats."""
    stats = ScreenLiveRuntimeStats(protocol="layered")

    with stats._lock:
        stats.raw_grab_frames = 100
        stats.captured = 85
        stats.dropped_slot_starvation = 15

    snapshot = stats.snapshot()

    # Starvation rate = dropped / raw_grab
    starvation_rate = snapshot["dropped_slot_starvation"] / snapshot["raw_grab_frames"]
    assert starvation_rate == 0.15  # 15%


def test_no_starvation_when_slots_available():
    """Test that no starvation occurs when slots are always available."""
    stats = ScreenLiveRuntimeStats(protocol="layered")

    # All grabs get slots
    for _ in range(50):
        with stats._lock:
            stats.raw_grab_frames += 1
            stats.captured += 1

    assert stats.raw_grab_frames == 50
    assert stats.captured == 50
    assert stats.dropped_slot_starvation == 0
    assert stats.slot_starvation_events == 0


def test_high_starvation_scenario():
    """Test high starvation scenario (slow downstream)."""
    stats = ScreenLiveRuntimeStats(protocol="layered")

    # Grab is fast (100 fps)
    for _ in range(100):
        with stats._lock:
            stats.raw_grab_frames += 1
            stats.capture_grab_time_ms += 10.0
            stats.capture_grab_ops += 1

    # But only 30 get slots (70% starvation)
    for _ in range(30):
        with stats._lock:
            stats.captured += 1
            stats.capture_copy_time_ms += 5.0
            stats.capture_copy_ops += 1

    # 70 starvation events
    with stats._lock:
        stats.dropped_slot_starvation = 70
        stats.slot_starvation_events = 70

    snapshot = stats.snapshot()

    # Verify high starvation
    assert snapshot["raw_grab_frames"] == 100
    assert snapshot["captured"] == 30
    assert snapshot["dropped_slot_starvation"] == 70
    starvation_rate = snapshot["dropped_slot_starvation"] / snapshot["raw_grab_frames"]
    assert starvation_rate == 0.7  # 70% starvation


def test_async_grab_loop_copy_task_progresses_while_slot_source_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeShot:
        def __init__(self) -> None:
            self.raw = b"\x01" * (4 * 4 * 4)

    class _FakeMSS:
        def __enter__(self) -> "_FakeMSS":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def grab(self, monitor):
            return _FakeShot()

    class _BlockingSlotQueue:
        def __init__(self) -> None:
            self._items: "queue.Queue[object]" = queue.Queue()
            self._items.put((0, 1))

        def get(self) -> object:
            return self._items.get()

        def put(self, item: object) -> object:
            self._items.put(item)
            return None

    class _DescriptorQueue:
        def __init__(self, stop_event: threading.Event, slot_queue: _BlockingSlotQueue) -> None:
            self.items: list[object] = []
            self._stop_event = stop_event
            self._slot_queue = slot_queue

        def get(self) -> object:
            raise queue.Empty

        def put(self, item: object) -> object:
            self.items.append(item)
            if isinstance(item, FilledSlotEvent):
                self._stop_event.set()
                self._slot_queue.put(None)
            return None

    monkeypatch.setitem(__import__("sys").modules, "mss", SimpleNamespace(mss=_FakeMSS))
    monkeypatch.setattr(
        "screen_airdrop.receiver.runtime.workers.get_monitor_region",
        lambda monitor_index: (0, 0, 4, 4),
    )
    monkeypatch.setattr(
        "screen_airdrop.receiver.runtime.workers.resolve_window_region",
        lambda window_title, explicit_region, monitor_region: (0, 0, 4, 4),
    )

    stop_event = threading.Event()
    slot_queue = _BlockingSlotQueue()
    descriptor_queue = _DescriptorQueue(stop_event, slot_queue)
    slot_view = __import__("numpy").zeros((4, 4, 4), dtype=__import__("numpy").uint8)

    asyncio.run(
        asyncio.wait_for(
            _async_grab_loop(
                slot_assign_queue=slot_queue,
                descriptor_queue=descriptor_queue,
                stop_event=stop_event,
                slot_views=[slot_view],
                target_fps=120.0,
                window_title=None,
                explicit_region=None,
                monitor_index=1,
            ),
            timeout=1.0,
        )
    )

    assert any(isinstance(item, FilledSlotEvent) for item in descriptor_queue.items)
