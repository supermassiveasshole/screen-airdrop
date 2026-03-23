"""Fixed-slot subprocess runtime for live screen capture."""

import asyncio
import multiprocessing as mp
import os
import threading
import time
from collections.abc import Mapping
from multiprocessing import shared_memory
from multiprocessing.process import BaseProcess
from typing import Any, Dict, List, Optional, Protocol, Tuple, cast

import numpy as np

from screen_airdrop.common.transport.protocol_basic import DEFAULT_GRID_H, DEFAULT_GRID_W
from screen_airdrop.receiver.debug.snapshot import DebugSnapshotManager
from screen_airdrop.receiver.information import ChunkAssembler
from screen_airdrop.receiver.locator.state_machine import GeometryState, GeometryTracker
from screen_airdrop.receiver.locator.window import resolve_window_region
from screen_airdrop.receiver.pipeline.base import BasePipeline
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
from screen_airdrop.receiver.runtime.screen_capture import get_monitor_region
from screen_airdrop.receiver.runtime.slot_manager import SlotManager
from screen_airdrop.receiver.runtime.stats import ScreenLiveRuntimeStats
from screen_airdrop.receiver.runtime.workers import (
    decode_worker_main,
    dump_worker_main,
    grab_process_main,
    prep_process_main,
)
from screen_airdrop.receiver.transport.layered.observability import (
    make_protocol_report_adapter,
)

# Public exports for the live pipeline module
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
    def accumulate_failure(
        self, error: str, *, failure_class: str, trace: Optional[Mapping[str, object]]
    ) -> None: ...


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


def _put_queue_sentinel(q: object) -> None:
    """Best-effort enqueue of a shutdown sentinel."""
    if q is None:
        return
    if hasattr(q, "put_nowait"):
        try:
            cast(Any, q).put_nowait(None)
            return
        except Exception:
            pass
    if hasattr(q, "put"):
        try:
            cast(Any, q).put(None)
        except Exception:
            pass


def _process_still_alive(proc: BaseProcess) -> bool:
    """Best-effort liveness check that tolerates half-closed process handles."""
    try:
        return proc.is_alive()
    except Exception:
        return False


def _unexpected_process_exit(proc: Optional[BaseProcess]) -> Optional[int]:
    """Return unexpected exit code for a live-runtime worker, if any."""
    if proc is None:
        return None
    try:
        if proc.exitcode is None:
            return None
        return int(proc.exitcode)
    except Exception:
        return None


class ScreenLiveRuntime(BasePipeline):
    """Fixed-slot subprocess runtime for live screen capture.

    实现 BasePipeline 接口，提供多进程高性能 pipeline。
    """

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
        manual_mode: bool = False,
        decode_workers: int = 1,
        frame_queue_size: int = 32,
        result_queue_size: int = 256,
        capture_fps: float = 30.0,
        capture_dump_dir: Optional[str] = None,
        capture_dump_max_frames: int = 0,
        debug_dir: Optional[str] = None,
        debug_interval: float = 1.0,
        debug_max_frames: int = 30,
        prep_process: int = 0,
        initial_search_roi: Optional[Tuple[int, int, int, int]] = None,
        on_frame_callback: Optional[Any] = None,
    ) -> None:
        if int(prep_process) not in (0, 1):
            raise ValueError("prep_process must be 0 or 1")
        if int(frame_queue_size) <= 0:
            raise ValueError("frame_queue_size must be positive")
        if int(result_queue_size) <= 0:
            raise ValueError("result_queue_size must be positive")

        # Initialize BasePipeline
        super().__init__(protocol)

        # Create report_collector (will be initialized in start() after assembler is available)
        self.report_collector = None

        self._capture = capture
        self._assembler = assembler
        self._protocol = protocol
        self._grid_w = grid_w
        self._grid_h = grid_h
        self._guard_band = guard_band
        self._corner_size = corner_size
        self._manual_mode = manual_mode
        self._decode_workers = max(1, int(decode_workers))
        self._frame_queue_size = int(frame_queue_size)
        self._result_queue_size = int(result_queue_size)
        self._capture_fps = capture_fps
        self._prep_processes = int(prep_process)
        self._dump_dir = capture_dump_dir
        self._dump_max_frames = max(0, int(capture_dump_max_frames))
        self._initial_search_roi = initial_search_roi
        self._user_on_frame_callback = on_frame_callback
        self._debug_snapshot_manager = (
            DebugSnapshotManager(
                debug_dir=debug_dir,
                debug_max_frames=max(1, int(debug_max_frames)),
                debug_interval=max(0.0, float(debug_interval)),
            )
            if debug_dir
            else None
        )
        self._on_frame_callback = (
            self._handle_frame_completion
            if self._debug_snapshot_manager is not None or self._user_on_frame_callback is not None
            else None
        )
        self._ctx = mp.get_context("spawn")
        self._stop_event = threading.Event()
        self.done_event = threading.Event()
        self.error: Optional[Exception] = None
        self.stats = ScreenLiveRuntimeStats(protocol=protocol)
        self.stats.protocol_report_adapter = cast(
            ProtocolReportAdapterProtocol, make_protocol_report_adapter(protocol)
        )
        self.stats.prep_mode = "process" if self._prep_processes > 0 else "async"
        self.stats.prep_processes = self._prep_processes
        monitor_region = get_monitor_region(int(self._capture.monitor_index))
        x, y, w, h = resolve_window_region(
            window_title=self._capture.window_title,
            explicit_region=self._capture.region,
            monitor_region=monitor_region,
        )
        self._capture.active_region = (x, y, w, h)
        if os.getenv("SCREEN_AIRDROP_RUNTIME_DEBUG", "").lower() not in ("", "0", "false", "no"):
            import sys
            import time

            print(
                "[runtime-debug "
                f"pid={os.getpid()} stage=runtime_region t={time.time():.3f}] "
                f"capture_region={self._capture.region} "
                f"active_region={self._capture.active_region} "
                f"monitor_region={monitor_region}",
                file=sys.stderr,
                flush=True,
            )
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
        # Use RGBA (4 channels) for zero-copy from MSS (29x faster)
        self._slot_bytes = self._width * self._height * 4
        self._slots = [
            shared_memory.SharedMemory(create=True, size=self._slot_bytes)
            for _ in range(self._slot_count)
        ]

        # Note: We do NOT unregister from resource_tracker. Let it handle cleanup automatically.
        # Manual unlink in _shutdown_processes() will clean up the shared memory segments.

        self._slot_views = [
            np.ndarray((self._height, self._width, 4), dtype=np.uint8, buffer=slot.buf)
            for slot in self._slots
        ]
        self._prep_roi = clip_roi_to_frame(
            self._initial_search_roi,
            frame_width=self._width,
            frame_height=self._height,
        )
        self._slot_registry = SlotManager([slot.name for slot in self._slots])

        # Create locator function based on mode
        from screen_airdrop.receiver.locator.factory import build_frame_locator

        self._stream_id = "screen:0"
        locator = build_frame_locator(
            grid_w=self._grid_w,
            grid_h=self._grid_h,
            guard_band=self._guard_band,
            corner_size=self._corner_size,
            initial_roi=self._initial_search_roi,
            manual_mode=self._manual_mode,
        )

        # Create GeometryTracker with integrated locator
        self._geometry_tracker = GeometryTracker(
            locator=locator,
            stream_id=self._stream_id,
            search_policy="roi_only" if self._manual_mode else "roi_then_expand",
            fixed_roi=self._initial_search_roi if self._manual_mode else None,
            locator_confidence_threshold=0.55,
        )
        self._last_fingerprint: Optional[bytes] = None
        self._next_worker = 0
        # Use ctx.SimpleQueue for cross-process queues
        self._grab_slot_queue = self._ctx.SimpleQueue()
        self._grab_event_queue = self._ctx.Queue(maxsize=self._frame_queue_size)
        self._prep_input_queue = (
            self._ctx.Queue(maxsize=self._frame_queue_size) if self._prep_processes > 0 else None
        )
        self._prep_output_queue = (
            self._ctx.Queue(maxsize=self._frame_queue_size) if self._prep_processes > 0 else None
        )
        self._decode_assignment_queues = [
            self._ctx.Queue(maxsize=self._frame_queue_size) for _ in range(self._decode_workers)
        ]
        self._decode_result_queue = self._ctx.Queue(maxsize=self._result_queue_size)
        self._dump_queue = (
            self._ctx.SimpleQueue() if self._dump_dir and self._dump_max_frames > 0 else None
        )
        self._dump_event_queue = self._ctx.SimpleQueue() if self._dump_queue is not None else None
        self._proc_stop_event = self._ctx.Event()
        self._grab_process: Optional[BaseProcess] = None
        self._grab_thread: Optional[threading.Thread] = None
        self._prep_process: Optional[BaseProcess] = None
        self._decode_processes: List[BaseProcess] = []
        self._dump_process: Optional[BaseProcess] = None
        self._coord_thread = threading.Thread(
            target=self._run_coordinator, name="ScreenLiveCoordinator", daemon=False
        )
        self._prep_async_queue: Optional[asyncio.Queue[FilledSlotEvent | None]] = None
        self._coord_async_queue: Optional[asyncio.Queue[Tuple[str, object]]] = None
        self._shutdown_lock = threading.Lock()
        self._shutdown_complete = False

    def start(self) -> None:
        # Initialize report_collector now that assembler is available
        self.report_collector = self._create_report_collector(
            stats=self.stats,
            assembler=self._assembler,
        )

        self._start_processes()
        self._prime_grab_slots()
        self._coord_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._proc_stop_event.set()
        self._signal_shutdown_queues()

    def join(self, timeout: float = 10.0) -> None:
        self.stop()
        self._coord_thread.join(timeout=timeout)
        self._shutdown_processes()

    def wait(self, timeout: Optional[float] = None) -> bool:
        return self.done_event.wait(timeout=timeout)

    def check_errors(self) -> None:
        if self.error is not None:
            raise RuntimeError(str(self.error)) from self.error

        if self._stop_event.is_set():
            return

        grab_exit = _unexpected_process_exit(self._grab_process)
        if grab_exit is not None:
            raise RuntimeError(f"grab process exited unexpectedly with code {grab_exit}")

        prep_exit = _unexpected_process_exit(self._prep_process)
        if prep_exit is not None:
            raise RuntimeError(f"prep process exited unexpectedly with code {prep_exit}")

        for idx, proc in enumerate(self._decode_processes):
            decode_exit = _unexpected_process_exit(proc)
            if decode_exit is not None:
                raise RuntimeError(
                    f"decode worker {idx} exited unexpectedly with code {decode_exit}"
                )

        dump_exit = _unexpected_process_exit(self._dump_process)
        if dump_exit is not None:
            raise RuntimeError(f"dump process exited unexpectedly with code {dump_exit}")

    def snapshot(self) -> Dict[str, Any]:
        """获取 pipeline 统计快照（实现 BasePipeline 接口）。

        Returns:
            统一格式的统计字典
        """
        snap = self.stats.snapshot()
        snap.update(self._geometry_tracker.snapshot().as_dict())
        return snap

    def _start_processes(self) -> None:
        # Use process instead of thread for better isolation
        self._grab_process = self._ctx.Process(
            target=grab_process_main,
            kwargs={
                "slot_assign_queue": self._grab_slot_queue,
                "descriptor_queue": self._grab_event_queue,
                "stop_event": self._proc_stop_event,
                "slot_names": [slot.name for slot in self._slots],
                "width": self._width,
                "height": self._height,
                "target_fps": float(self._capture_fps),
                "window_title": self._capture.window_title,
                "explicit_region": self._capture.region,
                "monitor_index": int(self._capture.monitor_index),
            },
            daemon=False,
            name="ScreenLiveGrab",
        )
        self._grab_process.start()
        if (
            self._prep_processes > 0
            and self._prep_input_queue is not None
            and self._prep_output_queue is not None
        ):
            self._prep_process = self._ctx.Process(
                target=prep_process_main,
                kwargs={
                    "prep_input_queue": self._prep_input_queue,
                    "prep_output_queue": self._prep_output_queue,
                    "slot_names": [slot.name for slot in self._slots],
                    "width": self._width,
                    "height": self._height,
                    "prep_roi": self._prep_roi,
                },
                daemon=False,
                name="ScreenLivePrep",
            )
            self._prep_process.start()
        for worker_id in range(self._decode_workers):
            proc = self._ctx.Process(
                target=decode_worker_main,
                kwargs={
                    "worker_id": worker_id,
                    "assignment_queue": self._decode_assignment_queues[worker_id],
                    "result_queue": self._decode_result_queue,
                    "slot_names": [slot.name for slot in self._slots],
                    "width": self._width,
                    "height": self._height,
                    "protocol": self._protocol,
                    "grid_w": self._grid_w,
                    "grid_h": self._grid_h,
                    "guard_band": self._guard_band,
                    "corner_size": self._corner_size,
                },
                daemon=False,
                name=f"ScreenLiveDecode-{worker_id}",
            )
            proc.start()
            self._decode_processes.append(proc)
        if self._dump_queue is not None and self._dump_event_queue is not None and self._dump_dir:
            self._dump_process = self._ctx.Process(
                target=dump_worker_main,
                kwargs={
                    "dump_queue": self._dump_queue,
                    "dump_event_queue": self._dump_event_queue,
                    "slot_names": [slot.name for slot in self._slots],
                    "width": self._width,
                    "height": self._height,
                    "dump_dir": self._dump_dir,
                },
                daemon=False,
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

        # Ensure report_collector is initialized (should be done in start())
        if self.report_collector is None:
            raise RuntimeError("report_collector not initialized - call start() first")

        # Create prep strategy based on mode
        if self._prep_processes > 0:
            prep_strategy = ProcessPrepStrategy(self._prep_input_queue, self._prep_output_queue)
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
            report_collector=self.report_collector,
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

    def _handle_frame_completion(self, completion: DecodeCompletion) -> None:
        """Emit debug artifacts and user callbacks for a decoded frame."""
        if self._debug_snapshot_manager is not None:
            self._dump_frame_debug_snapshot(completion)
        if self._user_on_frame_callback is not None:
            self._user_on_frame_callback(completion)

    def _dump_frame_debug_snapshot(self, completion: DecodeCompletion) -> None:
        if self._debug_snapshot_manager is None:
            return
        try:
            frame = self._slot_views[completion.descriptor.slot_id][:, :, :3].copy()
            meta = completion.meta
            if isinstance(meta, dict):
                v31_meta = dict(meta)
            elif hasattr(meta, "__dict__"):
                v31_meta = dict(vars(meta))
            else:
                v31_meta = {}
            det_bbox_local = None
            if isinstance(v31_meta, dict):
                det_bbox_local = v31_meta.get("det_bbox")
            if det_bbox_local is None and meta is not None:
                det_bbox_local = getattr(meta, "det_bbox", None)
            layered_failure_trace = (
                dict(completion.context)
                if isinstance(completion.context, Mapping)
                else None
            )
            self._debug_snapshot_manager.maybe_dump(
                now=time.time(),
                threshold=128,
                dump_kwargs={
                    "frame_index": int(completion.descriptor.capture_index),
                    "frame": frame,
                    "forced_roi_local": self._initial_search_roi,
                    "forced_roi_abs": None,
                    "capture_region": self._capture.active_region,
                    "decode_error": completion.error or None,
                    "protocol_path_used": self._protocol,
                    "track_roi_local": self._geometry_tracker.get_current_roi(),
                    "det_bbox_local": det_bbox_local,
                    "manual_strict": self._manual_mode,
                    "v31_meta": v31_meta,
                    "grid_w": self._grid_w,
                    "grid_h": self._grid_h,
                    "locator_confidence_threshold": 0.55,
                    "control_plane_kinds": sorted(self._assembler.control_items.keys()),
                    "control_session": self._assembler.session_info,
                    "control_layout": self._assembler.layout_info,
                    "control_generation": self._assembler.generation_info,
                    "control_generations_seen": sorted(self._assembler.generations.keys()),
                    "decoded_chunk_id": (
                        int(completion.chunk_id) if int(completion.chunk_id) >= 0 else None
                    ),
                    "decoded_payload": completion.payload or None,
                    "layered_failure_trace": layered_failure_trace,
                    "protocol": self._protocol,
                },
            )
        except Exception:
            pass

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

    def _signal_shutdown_queues(self) -> None:
        """Unblock all queue readers so Ctrl+C can drain the runtime cleanly."""
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
            _put_queue_sentinel(q)

    def _shutdown_processes(self) -> None:
        with self._shutdown_lock:
            if self._shutdown_complete:
                return
            self._shutdown_complete = True

            self._stop_event.set()
            self._proc_stop_event.set()
            self._signal_shutdown_queues()

            # Phase 1: Wait for graceful exit after all readers are unblocked
            import multiprocessing.connection

            procs = [
                self._grab_process,
                self._prep_process,
                *self._decode_processes,
                self._dump_process,
            ]
            sentinels = []
            for proc in procs:
                if proc is not None and proc.sentinel is not None:
                    sentinels.append(proc.sentinel)

            if sentinels:
                # Wait up to 2 seconds for graceful exit
                multiprocessing.connection.wait(sentinels, timeout=2.0)

            # Phase 2: Terminate any remaining processes
            for proc in procs:
                if proc is None:
                    continue
                if _process_still_alive(proc):
                    proc.terminate()

            # Phase 3: Final wait for termination to complete
            if sentinels:
                multiprocessing.connection.wait(sentinels, timeout=1.0)

            # Phase 3.5: Escalate to SIGKILL for stubborn children.
            for proc in procs:
                if proc is None:
                    continue
                if not _process_still_alive(proc):
                    continue
                kill = getattr(proc, "kill", None)
                if callable(kill):
                    try:
                        kill()
                    except Exception:
                        pass
                else:
                    try:
                        proc.terminate()
                    except Exception:
                        pass

            if sentinels:
                multiprocessing.connection.wait(sentinels, timeout=1.0)

            # Phase 4: Reap processes explicitly before closing handles.
            for proc in procs:
                if proc is None:
                    continue
                try:
                    proc.join(timeout=1.0)
                except Exception:
                    pass

            # Phase 5: Close all process handles
            for proc in procs:
                if proc is None:
                    continue
                try:
                    proc.close()
                except Exception:
                    pass

            # Phase 6: Close all queues
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

            # Phase 7: Close and unlink shared memory
            for shm in self._slots:
                try:
                    shm.close()
                except Exception:
                    pass
                try:
                    shm.unlink()
                except Exception:
                    pass
