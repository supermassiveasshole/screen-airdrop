# pyright: reportArgumentType=false
from __future__ import annotations

import json
import multiprocessing as mp
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

from screen_airdrop.receiver.locator.basic import locate_frame_legacy
from screen_airdrop.receiver.locator.frame_locator import FrameLocator
from screen_airdrop.receiver.runtime.frame_preprocessor import (
    clip_roi_to_frame,
    compute_fingerprint,
)
from screen_airdrop.receiver.runtime.geometry_tracker import GeometryState, GeometryTracker
from screen_airdrop.receiver.runtime.pipeline_runner import PipelineRunner
from screen_airdrop.receiver.runtime.slot_manager import SlotManager
from screen_airdrop.receiver.runtime.workers import _meta_snapshot
from screen_airdrop.receiver.screen_live_runtime import (
    FrameSlotDescriptor,
    ScreenLiveRuntime,
    ScreenLiveRuntimeStats,
    _close_queue,
    _process_still_alive,
    _put_queue_sentinel,
)


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
    # Create a mock locator
    locator = FrameLocator(
        locator_func=locate_frame_legacy,
        grid_w=32,
        grid_h=18,
        guard_band=2,
        corner_size=9,
        initial_roi=None,
        fixed_roi=False,
    )

    tracker = GeometryTracker(
        locator=locator,
        locator_confidence_threshold=0.55,
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
    setattr(tracker, "_state", "locked")

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


def test_runtime_uses_per_worker_decode_assignment_queues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeShm:
        _next = 0

        def __init__(self, *, create: bool, size: int) -> None:
            assert create is True
            self.size = size
            self.name = f"fake-shm-{_FakeShm._next}"
            _FakeShm._next += 1
            self.buf = bytearray(size)

        def close(self) -> None:
            return None

        def unlink(self) -> None:
            return None

    monkeypatch.setattr(
        "screen_airdrop.receiver.screen_live_runtime.get_monitor_region",
        lambda monitor_index: (0, 0, 100, 100),
    )
    monkeypatch.setattr(
        "screen_airdrop.receiver.screen_live_runtime.resolve_window_region",
        lambda window_title, explicit_region, monitor_region: (0, 0, 100, 100),
    )
    monkeypatch.setattr(
        "screen_airdrop.receiver.screen_live_runtime.shared_memory.SharedMemory",
        _FakeShm,
    )

    runtime = ScreenLiveRuntime(
        capture=SimpleNamespace(
            monitor_index=1,
            window_title=None,
            region=None,
            active_region=None,
        ),
        assembler=SimpleNamespace(),
        decode_workers=3,
    )

    try:
        assert len(runtime._decode_assignment_queues) == 3
        assert len({id(q) for q in runtime._decode_assignment_queues}) == 3
    finally:
        for slot in runtime._slots:
            slot.close()


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


def test_meta_snapshot_preserves_layered_body_profile_fields() -> None:
    meta = SimpleNamespace(
        body_profile_id=3,
        body_profile_name="dense",
        control_trace={"bootstrap_attempt_count": 1},
        det_confidence=0.9,
        homography_rmse=1.25,
    )
    snap = _meta_snapshot(meta)
    assert getattr(snap, "body_profile_id") == 3
    assert getattr(snap, "body_profile_name") == "dense"


class _SentinelQueue:
    def __init__(self) -> None:
        self.items = []

    def put_nowait(self, item) -> None:
        self.items.append(item)


class _ClosableQueue:
    def __init__(self) -> None:
        self.calls = []

    def cancel_join_thread(self) -> None:
        self.calls.append("cancel_join_thread")

    def close(self) -> None:
        self.calls.append("close")

    def join_thread(self) -> None:
        self.calls.append("join_thread")


def _ignore_sigterm_forever(stop_event) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while not stop_event.is_set():
        time.sleep(0.05)


def test_stop_signals_all_runtime_queues() -> None:
    runtime = object.__new__(ScreenLiveRuntime)
    runtime_any = cast(Any, runtime)
    runtime_any._stop_event = SimpleNamespace(set=lambda: None)
    runtime_any._proc_stop_event = SimpleNamespace(set=lambda: None)
    runtime_any._grab_slot_queue = _SentinelQueue()
    runtime_any._grab_event_queue = _SentinelQueue()
    runtime_any._prep_input_queue = _SentinelQueue()
    runtime_any._prep_output_queue = _SentinelQueue()
    runtime_any._decode_assignment_queues = [_SentinelQueue(), _SentinelQueue()]
    runtime_any._decode_result_queue = _SentinelQueue()
    runtime_any._dump_queue = _SentinelQueue()
    runtime_any._dump_event_queue = _SentinelQueue()

    ScreenLiveRuntime.stop(runtime)

    queues = [
        runtime._grab_slot_queue,
        runtime._grab_event_queue,
        runtime._prep_input_queue,
        runtime._prep_output_queue,
        *runtime._decode_assignment_queues,
        runtime._decode_result_queue,
        runtime._dump_queue,
        runtime._dump_event_queue,
    ]
    for q in queues:
        assert q.items == [None]


def test_put_queue_sentinel_only_enqueues() -> None:
    q = _SentinelQueue()
    _put_queue_sentinel(q)
    assert q.items == [None]


def test_put_queue_sentinel_supports_simple_queue() -> None:
    q = mp.get_context("spawn").SimpleQueue()
    _put_queue_sentinel(q)
    assert q.get() is None


def test_close_queue_runs_full_queue_cleanup() -> None:
    q = _ClosableQueue()
    _close_queue(q)
    assert q.calls == ["cancel_join_thread", "close", "join_thread"]


def test_process_still_alive_tolerates_closed_process_handle() -> None:
    ctx = mp.get_context("spawn")
    proc = ctx.Process(target=time.sleep, args=(0.01,))
    proc.start()
    proc.join(timeout=1.0)
    proc.close()
    assert _process_still_alive(proc) is False


def test_pipeline_runner_idle_timer_requires_new_progress() -> None:
    runner = PipelineRunner(
        pipeline=SimpleNamespace(),
        assembler=SimpleNamespace(),
        max_seconds=0,
        max_idle_seconds=30,
        stats_interval=1.0,
    )

    initial_time = runner.last_good_time

    runner._refresh_last_good_time({"decode_ok": 1, "assembled": 0}, now=10.0)
    assert runner.last_good_time == 10.0

    runner._refresh_last_good_time({"decode_ok": 1, "assembled": 0}, now=20.0)
    assert runner.last_good_time == 10.0

    runner._refresh_last_good_time({"decode_ok": 1, "assembled": 1}, now=25.0)
    assert runner.last_good_time == 25.0
    assert initial_time != runner.last_good_time


def test_shutdown_processes_kills_stubborn_child() -> None:
    ctx = mp.get_context("spawn")
    stubborn_stop = ctx.Event()
    stubborn_proc = ctx.Process(target=_ignore_sigterm_forever, args=(stubborn_stop,))
    stubborn_proc.start()
    stubborn_pid = stubborn_proc.pid
    assert stubborn_pid is not None

    runtime = object.__new__(ScreenLiveRuntime)
    runtime_any = cast(Any, runtime)
    runtime_any._shutdown_lock = threading.Lock()
    runtime_any._shutdown_complete = False
    runtime_any._stop_event = SimpleNamespace(set=lambda: None)
    runtime_any._proc_stop_event = SimpleNamespace(set=lambda: None)
    runtime_any._signal_shutdown_queues = lambda: None
    runtime_any._grab_process = stubborn_proc
    runtime_any._prep_process = None
    runtime_any._decode_processes = []
    runtime_any._dump_process = None
    runtime_any._grab_slot_queue = None
    runtime_any._grab_event_queue = None
    runtime_any._prep_input_queue = None
    runtime_any._prep_output_queue = None
    runtime_any._decode_assignment_queues = []
    runtime_any._decode_result_queue = None
    runtime_any._dump_queue = None
    runtime_any._dump_event_queue = None
    runtime_any._slots = []

    ScreenLiveRuntime._shutdown_processes(runtime)

    deadline = time.time() + 3.0
    while time.time() < deadline and _pid_exists(stubborn_pid):
        time.sleep(0.05)

    assert _pid_exists(stubborn_pid) is False


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _collect_descendant_pids(root_pid: int) -> list[int]:
    descendants: set[int] = set()
    frontier = [root_pid]
    while frontier:
        current = frontier.pop()
        result = subprocess.run(
            ["pgrep", "-P", str(current)],
            check=False,
            capture_output=True,
            text=True,
        )
        children = [
            int(line.strip())
            for line in result.stdout.splitlines()
            if line.strip().isdigit()
        ]
        for child in children:
            if child not in descendants:
                descendants.add(child)
                frontier.append(child)
    return sorted(descendants)


def test_shutdown_probe_leaves_no_orphan_processes() -> None:
    helper = (
        Path(__file__).resolve().parents[1] / "helpers" / "runtime_shutdown_probe.py"
    )
    proc = subprocess.run(
        [sys.executable, str(helper)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    pids = list(payload["child_pids"])
    tracker_pid = payload.get("resource_tracker_pid")
    if tracker_pid is not None:
        pids.append(int(tracker_pid))

    deadline = time.time() + 3.0
    while time.time() < deadline and any(_pid_exists(pid) for pid in pids):
        time.sleep(0.05)

    leaked = [pid for pid in pids if _pid_exists(pid)]
    assert leaked == []


def test_sigint_probe_leaves_no_orphan_processes() -> None:
    helper = Path(__file__).resolve().parents[1] / "helpers" / "runtime_sigint_probe.py"
    proc = subprocess.Popen(
        [sys.executable, str(helper)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    first_line = proc.stdout.readline().strip()
    assert first_line
    payload = json.loads(first_line)

    proc.send_signal(signal.SIGINT)
    proc.wait(timeout=5.0)

    pids = list(payload["child_pids"])
    tracker_pid = payload.get("resource_tracker_pid")
    if tracker_pid is not None:
        pids.append(int(tracker_pid))

    deadline = time.time() + 3.0
    while time.time() < deadline and any(_pid_exists(pid) for pid in pids):
        time.sleep(0.05)

    leaked = [pid for pid in pids if _pid_exists(pid)]
    assert leaked == []


def test_real_runtime_sigint_leaves_no_orphan_processes() -> None:
    helper = Path(__file__).resolve().parents[1] / "helpers" / "runtime_real_sigint_probe.py"
    fake_modules = Path(__file__).resolve().parents[1] / "helpers" / "fake_modules"
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(fake_modules) if not existing else f"{fake_modules}{os.pathsep}{existing}"
    )
    proc = subprocess.Popen(
        [sys.executable, str(helper)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert proc.stdout is not None
    first_line = proc.stdout.readline().strip()
    assert first_line
    payload = json.loads(first_line)

    proc.send_signal(signal.SIGINT)
    proc.wait(timeout=8.0)

    pids = list(payload["child_pids"])
    tracker_pid = payload.get("resource_tracker_pid")
    if tracker_pid is not None:
        pids.append(int(tracker_pid))

    deadline = time.time() + 5.0
    while time.time() < deadline and any(_pid_exists(pid) for pid in pids):
        time.sleep(0.05)

    leaked = [pid for pid in pids if _pid_exists(pid)]
    assert leaked == []


def test_real_uv_cli_sigint_leaves_no_orphan_processes() -> None:
    fake_modules = Path(__file__).resolve().parents[1] / "helpers" / "fake_modules"
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(fake_modules) if not existing else f"{fake_modules}{os.pathsep}{existing}"
    )
    with tempfile.TemporaryDirectory(prefix="layered-live-runtime-captured-") as dump_dir:
        report_json = os.path.join(dump_dir, "report.json")
        proc = subprocess.Popen(
            [
                "uv",
                "run",
                "screen-airdrop-receiver",
                "--source",
                "screen",
                "--window-title",
                "screen-airdrop",
                "--protocol",
                "layered",
                "--module-grid",
                "240x144",
                # Interactive ROI selection is not automatable in tests; use
                # an equivalent fixed ROI to exercise the same runtime path.
                "--roi",
                "0,0,128,128",
                "--capture-fps",
                "55",
                "--decode-workers",
                "6",
                "--capture-dump-dir",
                dump_dir,
                "--capture-dump-max-frames",
                "32",
                "--max-idle-seconds",
                "30",
                "--report-json",
                report_json,
                "--prep-process",
                "1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            start_new_session=True,
        )
        try:
            deadline = time.time() + 8.0
            while time.time() < deadline:
                descendants = _collect_descendant_pids(proc.pid)
                if descendants:
                    break
                time.sleep(0.05)
            else:
                stdout, stderr = proc.communicate(timeout=2.0)
                raise AssertionError(
                    f"CLI did not spawn child processes in time.\nstdout:\n{stdout}\nstderr:\n{stderr}"
                )

            os.killpg(proc.pid, signal.SIGINT)
            proc.wait(timeout=10.0)

            deadline = time.time() + 5.0
            while time.time() < deadline and any(_pid_exists(pid) for pid in descendants):
                time.sleep(0.05)

            leaked = [pid for pid in descendants if _pid_exists(pid)]
            assert leaked == []
        finally:
            if proc.poll() is None:
                proc.kill()
