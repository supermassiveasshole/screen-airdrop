"""Fixed-slot subprocess runtime for live screen capture."""

import asyncio
import multiprocessing as mp
import queue
import signal
import threading
import time
from multiprocessing import shared_memory
from multiprocessing.process import BaseProcess
from types import SimpleNamespace
from typing import Any, List, Mapping, Optional, Protocol, Tuple, cast

import numpy as np

from screen_airdrop.common.control_plane import control_kind_from_wire_chunk_id
from screen_airdrop.common.protocol_basic import DEFAULT_GRID_H, DEFAULT_GRID_W, FRAME_DATA
from screen_airdrop.receiver.assembler import ChunkAssembler
from screen_airdrop.receiver.capture_mss import get_monitor_region
from screen_airdrop.receiver.protocol_observability import make_protocol_report_adapter
from screen_airdrop.receiver.runtime.events import (
    DecodeAssignment,
    DecodeCompletion,
    DumpCopyCompletion,
    DuplicateSlotEvent,
    FilledSlotEvent,
    FrameSlotDescriptor,
    PreparedSlotEvent,
    PrepFingerprintEvent,
)
from screen_airdrop.receiver.runtime.frame_preprocessor import (
    clip_roi_to_frame,
    compute_fingerprint,
)
from screen_airdrop.receiver.runtime.geometry_tracker import GeometryState, GeometryTracker
from screen_airdrop.receiver.runtime.slot_manager import SlotManager
from screen_airdrop.receiver.runtime.stats import ScreenLiveRuntimeStats
from screen_airdrop.receiver.runtime.workers import (
    _decode_worker_main,
    _dump_worker_main,
    _grab_thread_main,
    _prep_process_main,
)
from screen_airdrop.receiver.window_locator import resolve_window_region

# Re-export for backward compatibility
__all__ = [
    "ScreenLiveRuntime",
    "ScreenLiveRuntimeStats",
    "FrameSlotDescriptor",
    "FilledSlotEvent",
    "PreparedSlotEvent",
    "DuplicateSlotEvent",
    "PrepFingerprintEvent",
    "DecodeAssignment",
    "DecodeCompletion",
    "DumpCopyCompletion",
    "GeometryState",
]


# Suppress resource_tracker warnings for shared memory cleanup
# These warnings occur because child processes unregister shared memory to avoid
# double-cleanup, but resource_tracker still tries to clean up on exit.
# This is a known limitation of Python's multiprocessing shared_memory implementation.
# The warnings are harmless and don't affect functionality.
# To suppress them, set PYTHONWARNINGS=ignore or redirect stderr.
def _suppress_resource_tracker_warnings() -> None:
    """Document resource_tracker KeyError warnings."""
    pass


_suppress_resource_tracker_warnings()


_FINGERPRINT_H = 16
_FINGERPRINT_W = 24
_SLOT_FLAG_DUPLICATE = 1 << 0
_PREP_ROI_FRACTION = 0.8
_COORDINATOR_TICK = "__tick__"
_GRAB_OWNER = "grab"


class ProtocolReportAdapterProtocol(Protocol):
    def finalize_summary(self) -> Mapping[str, object]: ...
    def accumulate_success(self, meta: object) -> None: ...
    def accumulate_failure(self, error: str, *, failure_class: str, trace: Optional[Mapping[str, object]]) -> None: ...



def _close_queue(q: object) -> None:
    if q is None:
        return
    if hasattr(q, "cancel_join_thread"):
        try:
            cast(Any, q).cancel_join_thread()
        except Exception:
            pass
    if hasattr(q, "close"):
        try:
            cast(Any, q).close()
        except Exception:
            pass
    if hasattr(q, "join_thread"):
        try:
            cast(Any, q).join_thread()
        except Exception:
            pass


def _ignore_sigint_in_child() -> None:
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except Exception:
        pass


class ScreenLiveRuntime:
    def __init__(
        self,
        *,
        capture,
        assembler: ChunkAssembler,
        protocol: str = "basic",
        grid_w: int = DEFAULT_GRID_W,
        grid_h: int = DEFAULT_GRID_H,
        guard_band: int = 2,
        corner_size: int = 9,
        locator_engine: str = "auto",
        locator_confidence_threshold: float = 0.55,
        decode_workers: int = 1,
        capture_fps: float = 30.0,
        capture_dump_dir: Optional[str] = None,
        capture_dump_max_frames: int = 0,
        prep_process: int = 0,
        initial_search_roi: Optional[Tuple[int, int, int, int]] = None,
        on_frame_callback: Optional[Any] = None,
    ) -> None:
        if int(prep_process) not in (0, 1):
            raise ValueError("prep_process must be 0 or 1")
        self._capture = capture
        self._assembler = assembler
        self._protocol = protocol
        self._grid_w = grid_w
        self._grid_h = grid_h
        self._guard_band = guard_band
        self._corner_size = corner_size
        self._locator_engine = locator_engine
        self._locator_confidence_threshold = locator_confidence_threshold
        self._decode_workers = max(1, int(decode_workers))
        self._capture_fps = capture_fps
        self._prep_processes = int(prep_process)
        self._dump_dir = capture_dump_dir
        self._dump_max_frames = max(0, int(capture_dump_max_frames))
        self._initial_search_roi = initial_search_roi
        self._on_frame_callback = on_frame_callback
        self._ctx = mp.get_context("spawn")
        self._stop_event = threading.Event()
        self.done_event = threading.Event()
        self.error: Optional[Exception] = None
        self.stats = ScreenLiveRuntimeStats(protocol=protocol)
        self.stats.protocol_report_adapter = cast(ProtocolReportAdapterProtocol, make_protocol_report_adapter(protocol))
        self.stats.prep_mode = "process" if self._prep_processes > 0 else "async"
        self.stats.prep_processes = self._prep_processes
        monitor_region = get_monitor_region(int(self._capture.monitor_index))
        x, y, w, h = resolve_window_region(
            window_title=self._capture.window_title,
            explicit_region=self._capture.region,
            monitor_region=monitor_region,
        )
        self._capture.active_region = (x, y, w, h)
        self._width = int(w)
        self._height = int(h)
        # Slot count calculation:
        # - For low FPS (<10): decode_workers + 3 is enough
        # - For high FPS (>20): need 2x buffer to avoid grab starvation
        # - Formula: max(base, fps_based, decode_based)
        base_slots = 4
        fps_based_slots = int(self._capture_fps * 2) if self._capture_fps > 10 else 0
        decode_based_slots = self._decode_workers * 3 + 6
        self._slot_count = max(base_slots, fps_based_slots, decode_based_slots) + (
            1 if self._dump_dir and self._dump_max_frames > 0 else 0
        )
        self._slot_bytes = self._width * self._height * 3
        self._slots = [shared_memory.SharedMemory(create=True, size=self._slot_bytes) for _ in range(self._slot_count)]

        # Note: We do NOT unregister from resource_tracker. Let it handle cleanup automatically.
        # Manual unlink in _shutdown_processes() will clean up the shared memory segments.

        self._slot_views = [
            np.ndarray((self._height, self._width, 3), dtype=np.uint8, buffer=slot.buf)
            for slot in self._slots
        ]
        self._prep_roi = clip_roi_to_frame(
            self._initial_search_roi,
            frame_width=self._width,
            frame_height=self._height,
        )
        self._slot_registry = SlotManager([slot.name for slot in self._slots])
        self._geometry_tracker = GeometryTracker(
            locator_confidence_threshold=self._locator_confidence_threshold,
            lock_fail_reacquire_threshold=5,
        )
        self._last_fingerprint: Optional[bytes] = None
        self._next_worker = 0
        self._grab_slot_queue: queue.SimpleQueue[object] = queue.SimpleQueue()
        self._grab_event_queue: queue.SimpleQueue[object] = queue.SimpleQueue()
        self._prep_input_queue = self._ctx.SimpleQueue() if self._prep_processes > 0 else None
        self._prep_output_queue = self._ctx.SimpleQueue() if self._prep_processes > 0 else None
        self._decode_assignment_queues = [self._ctx.SimpleQueue() for _ in range(self._decode_workers)]
        self._decode_result_queue = self._ctx.SimpleQueue()
        self._dump_queue = self._ctx.SimpleQueue() if self._dump_dir and self._dump_max_frames > 0 else None
        self._dump_event_queue = self._ctx.SimpleQueue() if self._dump_queue is not None else None
        self._proc_stop_event = self._ctx.Event()
        self._grab_process: Optional[BaseProcess] = None
        self._grab_thread: Optional[threading.Thread] = None
        self._prep_process: Optional[BaseProcess] = None
        self._decode_processes: List[BaseProcess] = []
        self._dump_process: Optional[BaseProcess] = None
        self._coord_thread = threading.Thread(target=self._run_coordinator, name="ScreenLiveCoordinator", daemon=False)
        self._stream_id = "screen:0"
        self._prep_async_queue: Optional[asyncio.Queue[FilledSlotEvent | None]] = None
        self._coord_async_queue: Optional[asyncio.Queue[Tuple[str, object]]] = None
        self._shutdown_lock = threading.Lock()
        self._shutdown_complete = False

    def start(self) -> None:
        self._start_processes()
        self._prime_grab_slots()
        self._coord_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._proc_stop_event.set()
        # Send sentinel values to unblock queue.get() calls in asyncio.to_thread
        for q in [self._grab_event_queue, self._prep_output_queue, self._decode_result_queue, self._dump_event_queue]:
            if q is not None:
                try:
                    q.put_nowait(None)
                except Exception:
                    pass

    def join(self, timeout: float = 10.0) -> None:
        self.stop()
        self._coord_thread.join(timeout=timeout)
        self._shutdown_processes()

    def wait(self, timeout: Optional[float] = None) -> bool:
        return self.done_event.wait(timeout=timeout)

    def check_errors(self) -> None:
        if self.error is not None:
            raise RuntimeError(str(self.error)) from self.error

    def _start_processes(self) -> None:
        self._grab_thread = threading.Thread(
            target=_grab_thread_main,
            kwargs={
                "slot_assign_queue": self._grab_slot_queue,
                "descriptor_queue": self._grab_event_queue,
                "stop_event": self._stop_event,
                "slot_views": self._slot_views,
                "target_fps": float(self._capture_fps),
                "window_title": self._capture.window_title,
                "explicit_region": self._capture.region,
                "monitor_index": int(self._capture.monitor_index),
            },
            daemon=True,
            name="ScreenLiveGrab",
        )
        self._grab_thread.start()
        if self._prep_processes > 0 and self._prep_input_queue is not None and self._prep_output_queue is not None:
            self._prep_process = self._ctx.Process(
                target=_prep_process_main,
                kwargs={
                    "prep_input_queue": self._prep_input_queue,
                    "prep_output_queue": self._prep_output_queue,
                    "stop_event": self._proc_stop_event,
                    "slot_names": [slot.name for slot in self._slots],
                    "width": self._width,
                    "height": self._height,
                    "prep_roi": self._prep_roi,
                },
                daemon=True,
                name="ScreenLivePrep",
            )
            self._prep_process.start()
        for worker_id in range(self._decode_workers):
            proc = self._ctx.Process(
                target=_decode_worker_main,
                kwargs={
                    "worker_id": worker_id,
                    "assignment_queue": self._decode_assignment_queues[worker_id],
                    "result_queue": self._decode_result_queue,
                    "stop_event": self._proc_stop_event,
                    "slot_names": [slot.name for slot in self._slots],
                    "width": self._width,
                    "height": self._height,
                    "protocol": self._protocol,
                    "grid_w": self._grid_w,
                    "grid_h": self._grid_h,
                    "guard_band": self._guard_band,
                    "corner_size": self._corner_size,
                    "locator_engine": self._locator_engine,
                    "locator_confidence_threshold": self._locator_confidence_threshold,
                },
                daemon=True,
                name=f"ScreenLiveDecode-{worker_id}",
            )
            proc.start()
            self._decode_processes.append(proc)
        if self._dump_queue is not None and self._dump_event_queue is not None and self._dump_dir:
            self._dump_process = self._ctx.Process(
                target=_dump_worker_main,
                kwargs={
                    "dump_queue": self._dump_queue,
                    "dump_event_queue": self._dump_event_queue,
                    "stop_event": self._proc_stop_event,
                    "slot_names": [slot.name for slot in self._slots],
                    "width": self._width,
                    "height": self._height,
                    "dump_dir": self._dump_dir,
                },
                daemon=True,
                name="ScreenLiveDump",
            )
            self._dump_process.start()

    def _prime_grab_slots(self) -> None:
        writer_owner = _GRAB_OWNER
        for _ in range(self._slot_count):
            allocated = self._slot_registry.allocate_for_grab(writer_owner)
            if allocated is None:
                break
            slot_id, generation, _ = allocated
            self._grab_slot_queue.put((slot_id, generation))

    def _run_coordinator(self) -> None:
        """Run coordinator event loop."""
        from screen_airdrop.receiver.runtime.coordinator import RuntimeCoordinator
        from screen_airdrop.receiver.runtime.prep_strategy import (
            AsyncPrepStrategy,
            ProcessPrepStrategy,
        )

        # Create prep strategy based on mode
        if self._prep_processes > 0:
            prep_strategy = ProcessPrepStrategy(
                self._prep_input_queue, self._prep_output_queue
            )
        else:
            prep_strategy = AsyncPrepStrategy(
                slot_views=self._slot_views,
                prep_roi=self._prep_roi,
            )

        # Create coordinator
        coordinator = RuntimeCoordinator(
            slot_manager=self._slot_registry,
            geometry_tracker=self._geometry_tracker,
            stats=self.stats,
            assembler=self._assembler,
            prep_strategy=prep_strategy,
            grab_slot_queue=self._grab_slot_queue,
            grab_event_queue=self._grab_event_queue,
            prep_output_queue=self._prep_output_queue,
            decode_assignment_queues=self._decode_assignment_queues,
            decode_result_queue=self._decode_result_queue,
            dump_queue=self._dump_queue,
            dump_event_queue=self._dump_event_queue,
            stop_event=self._stop_event,
            stream_id=self._stream_id,
            on_frame_callback=self._on_frame_callback,
        )

        try:
            asyncio.run(coordinator.run())
        except Exception as exc:
            self.error = exc
            self._stop_event.set()
        finally:
            self._shutdown_processes()
            self.done_event.set()  # Signal that runtime has completed

    async def _run_prep(self, filled: FilledSlotEvent) -> PrepFingerprintEvent:
        descriptor = filled.descriptor
        if not self._slot_registry.descriptor_matches_current(descriptor):
            raise RuntimeError("stale filled descriptor reached prep")
        # Extract ROI from frame
        x, y, w, h = self._prep_roi
        frame_roi = self._slot_views[descriptor.slot_id][y : y + h, x : x + w]
        t0 = time.perf_counter()
        fingerprint_array = await asyncio.to_thread(compute_fingerprint, frame_roi)
        t1 = time.perf_counter()
        return PrepFingerprintEvent(
            descriptor=descriptor,
            fingerprint=cast(np.ndarray, fingerprint_array).tobytes(),
            fingerprint_ms=(t1 - t0) * 1000.0,
        )

    def _accept_decoded_chunk(self, completion: DecodeCompletion, decoded_ts: float) -> None:
        if completion.frame_type == FRAME_DATA:
            control_kind = control_kind_from_wire_chunk_id(completion.chunk_id)
            if control_kind is not None:
                with self.stats._lock:
                    if self.stats.first_new_chunk_ts is None:
                        self.stats.startup_control_frames_decoded += 1
                try:
                    self._assembler.add_control(control_kind, completion.payload)
                except Exception:
                    pass
            elif completion.chunk_id > 0:
                is_new_chunk = completion.chunk_id not in self._assembler.chunks
                self._assembler.add(completion.chunk_id, completion.payload)
                with self.stats._lock:
                    if is_new_chunk:
                        self.stats.decoded_new_chunks += 1
                        self.stats.assembled += 1
                        self.stats.assembled_bytes += len(completion.payload)
                        if self.stats.first_new_chunk_ts is None:
                            self.stats.first_new_chunk_ts = decoded_ts
                    else:
                        self.stats.decoded_duplicate_chunks += 1
        else:
            with self.stats._lock:
                if self.stats.first_new_chunk_ts is None:
                    self.stats.startup_sync_frames_decoded += 1
        if self._on_frame_callback is not None:
            try:
                self._on_frame_callback(
                    SimpleNamespace(
                        chunk_id=completion.chunk_id,
                        payload=completion.payload,
                        frame_id=completion.frame_id,
                        frame_type=completion.frame_type,
                        meta=completion.meta,
                        decoded_ts=decoded_ts,
                    )
                )
            except Exception:
                pass

    def _signal_control_sentinels(self) -> None:
        for q in (
            self._grab_slot_queue,
            self._grab_event_queue,
            self._prep_input_queue,
            self._prep_output_queue,
            *self._decode_assignment_queues,
            self._decode_result_queue,
            self._dump_queue,
            self._dump_event_queue,
        ):
            if q is None:
                continue
            try:
                q.put(None)
            except Exception:
                pass

    def _check_process_health(self) -> None:
        if self._grab_thread is not None and not self._grab_thread.is_alive() and not self._stop_event.is_set():
            self._slot_registry.reclaim_writer_owner(_GRAB_OWNER)
            self.error = RuntimeError("grab thread exited unexpectedly")
            self._stop_event.set()
        if self._prep_process is not None and not self._prep_process.is_alive() and self._prep_process.exitcode not in (0, None):
            self.error = RuntimeError(f"prep process exited with code {self._prep_process.exitcode}")
            self._stop_event.set()
        for idx, proc in enumerate(self._decode_processes):
            if not proc.is_alive() and proc.exitcode not in (0, None):
                self._slot_registry.reclaim_decode_owner(idx)
                self.error = RuntimeError(f"decode worker {idx} exited with code {proc.exitcode}")
                self._stop_event.set()
        if self._dump_process is not None and not self._dump_process.is_alive() and self._dump_process.exitcode not in (0, None):
            self._slot_registry.reclaim_dump_reader()

    def _shutdown_processes(self) -> None:
        with self._shutdown_lock:
            if self._shutdown_complete:
                return
            self._shutdown_complete = True

            # First, send stop signals to all queues to unblock workers
            for q in [
                self._prep_input_queue,
                self._prep_output_queue,
                *self._decode_assignment_queues,
                self._decode_result_queue,
                self._dump_queue,
            ]:
                if q is not None:
                    try:
                        q.put_nowait(None)
                    except Exception:
                        pass

            # Give processes a brief moment to exit gracefully
            import time
            time.sleep(0.05)

            # Terminate processes that are still alive
            for proc in [self._prep_process, *self._decode_processes, self._dump_process]:
                if proc is None:
                    continue
                if proc.is_alive():
                    proc.terminate()

            # Wait for all processes to actually exit using sentinels
            import multiprocessing.connection
            sentinels = []
            for proc in [self._prep_process, *self._decode_processes, self._dump_process]:
                if proc is not None and proc.sentinel is not None:
                    sentinels.append(proc.sentinel)

            if sentinels:
                # Wait for all sentinels with timeout
                multiprocessing.connection.wait(sentinels, timeout=1.0)

            # Join grab thread
            if self._grab_thread is not None:
                self._grab_thread.join(timeout=0.5)

            # Close all processes
            for proc in [self._prep_process, *self._decode_processes, self._dump_process]:
                if proc is None:
                    continue
                try:
                    proc.close()
                except Exception:
                    pass

            # Close all queues
            for q in [
                self._grab_slot_queue,
                self._grab_event_queue,
                self._prep_input_queue,
                self._prep_output_queue,
                *self._decode_assignment_queues,
                self._decode_result_queue,
                self._dump_queue,
                self._dump_event_queue,
            ]:
                _close_queue(q)

            # Close and unlink shared memory
            for shm in self._slots:
                try:
                    shm.close()
                except Exception:
                    pass
                try:
                    shm.unlink()
                except Exception:
                    pass

    def _classify_failure(self, decode_error: str) -> str:
        raw = str(decode_error).strip().lower()
        if not raw:
            return ""
        if "payload rs decode failed" in raw or "payload crc mismatch" in raw or "crc mismatch" in raw:
            return "payload"
        if "header rs decode failed" in raw or "bad v3 magic" in raw or "format parity mismatch" in raw or "bootstrap" in raw:
            return "header"
        if "locator" in raw or "no_finder" in raw or "finder" in raw:
            return "locator"
        return "unknown"
