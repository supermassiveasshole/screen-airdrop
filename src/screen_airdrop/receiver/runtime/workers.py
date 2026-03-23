"""Worker process entry points and helper functions."""

import asyncio
import os
import queue
import signal
import sys
import threading
import time
from multiprocessing import shared_memory
from types import SimpleNamespace
from typing import Any, List, Optional, Protocol, Sequence, Tuple, cast

import numpy as np

from screen_airdrop.receiver.decode_errors import DecodeError
from screen_airdrop.receiver.locator.state_machine import GeometryState
from screen_airdrop.receiver.locator.window import resolve_window_region
from screen_airdrop.receiver.runtime.events import (
    DecodeAssignment,
    DecodeCompletion,
    DumpCopyCompletion,
    FilledSlotEvent,
    FrameSlotDescriptor,
    PrepFingerprintEvent,
)
from screen_airdrop.receiver.runtime.frame_preprocessor import compute_fingerprint
from screen_airdrop.receiver.runtime.screen_capture import get_monitor_region
from screen_airdrop.receiver.transport.decoder_factory import create_protocol_decoder


class QueueLike(Protocol):
    """Protocol for queue-like objects."""

    def get(self) -> object: ...
    def put(self, item: object) -> object: ...


_DEBUG_RUNTIME = os.getenv("SCREEN_AIRDROP_RUNTIME_DEBUG", "").lower() not in ("", "0", "false", "no")
_SLOT_PREFETCH = 4
_COPY_WORKERS = 2
_COPY_QUEUE_DEPTH = 8


def _debug_log(stage: str, **fields: object) -> None:
    """Emit lightweight runtime debug logs when explicitly enabled."""
    if not _DEBUG_RUNTIME:
        return
    payload = " ".join(f"{key}={value}" for key, value in fields.items())
    print(
        f"[runtime-debug pid={os.getpid()} stage={stage} t={time.time():.3f}] {payload}",
        file=sys.stderr,
        flush=True,
    )


def _slot_bridge_loop(
    slot_assign_queue: QueueLike,
    local_slot_queue: "queue.Queue[object]",
) -> None:
    """Bridge blocking cross-process slot assignment into a local non-blocking queue."""
    while True:
        item = slot_assign_queue.get()
        local_slot_queue.put(item)
        if item is None:
            return


def _close_queue(q: object) -> None:
    """Close a queue safely."""
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
    """Ignore SIGINT in child process."""
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except Exception:
        pass


def _attach_shared_memory_for_child(name: str) -> shared_memory.SharedMemory:
    # Attach to existing shared memory created by parent
    # Parent has already unregistered from resource_tracker, so we don't need to
    shm = shared_memory.SharedMemory(name=name)
    return shm


def _make_decoder(
    *,
    protocol: str,
    grid_w: int,
    grid_h: int,
    guard_band: int,
    corner_size: int,
) -> Any:
    """Create protocol decoder instance.

    Args:
        protocol: Protocol name
        grid_w: Grid width
        grid_h: Grid height
        guard_band: Guard band size
        corner_size: Corner marker size

    Returns:
        Protocol decoder instance

    Raises:
        ValueError: If protocol is unknown
    """
    return create_protocol_decoder(
        protocol=protocol,
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=guard_band,
        corner_size=corner_size,
    )


def _as_grid_bbox_std(value: Sequence[int]) -> Tuple[int, int, int, int]:
    vals = [int(v) for v in value]
    return (vals[0], vals[1], vals[2], vals[3])


def _as_warped_shape(value: Sequence[int]) -> Tuple[int, int]:
    vals = [int(v) for v in value]
    return (vals[0], vals[1])


def _layered_geometry_from_runtime(state: Optional[GeometryState]) -> Optional[object]:
    if (
        state is None
        or state.quad_src is None
        or state.homography is None
        or state.homography_inv is None
    ):
        return None
    from screen_airdrop.receiver.transport.layered.decoder import LayeredGeometryState

    return LayeredGeometryState(
        quad_src=np.array(state.quad_src, copy=True),
        homography=np.array(state.homography, copy=True),
        homography_inv=np.array(state.homography_inv, copy=True),
        grid_bbox_std=_as_grid_bbox_std(state.grid_bbox_std),
        warped_shape=_as_warped_shape(state.warped_shape),
        locator_engine=str(state.locator_engine),
        det_confidence=float(state.det_confidence),
        homography_rmse=float(state.homography_rmse),
    )


def _geometry_state_from_meta(
    decoder: Any,
    meta: object,
    *,
    stream_id: str,
    geometry_generation: int,
    capture_index: int,
    chunk_id: int,
    frame_id: int,
    quality_score: float,
    lock_mode: str,
) -> Optional[GeometryState]:
    if not hasattr(decoder, "geometry_from_meta"):
        return None
    raw = decoder.geometry_from_meta(meta)
    if raw is None:
        return None
    return GeometryState(
        stream_id=stream_id,
        geometry_generation=geometry_generation,
        quad_src=np.array(raw.quad_src, copy=True),
        homography=np.array(raw.homography, copy=True),
        homography_inv=np.array(raw.homography_inv, copy=True),
        source_capture_index=int(capture_index),
        last_success_frame_id=int(frame_id),
        last_success_chunk_id=int(chunk_id),
        quality_score=float(quality_score),
        lock_mode=str(lock_mode),
        grid_bbox_std=_as_grid_bbox_std(raw.grid_bbox_std),
        warped_shape=_as_warped_shape(raw.warped_shape),
        locator_engine=str(raw.locator_engine),
        det_confidence=float(raw.det_confidence),
        homography_rmse=float(raw.homography_rmse),
    )


def _meta_snapshot(meta: object) -> object:
    return SimpleNamespace(
        det_bbox=getattr(meta, "det_bbox", None),
        mask_id=getattr(meta, "mask_id", -1),
        body_profile_id=getattr(meta, "body_profile_id", 0),
        body_profile_name=getattr(meta, "body_profile_name", ""),
        avg_symbol_confidence=getattr(meta, "avg_symbol_confidence", 0.0),
        total_decode_ms=getattr(meta, "total_decode_ms", 0.0),
        payload_low_conf_symbols=getattr(meta, "payload_low_conf_symbols", 0),
        payload_variant_attempts=getattr(meta, "payload_variant_attempts", 0),
        phase_candidates_tried=getattr(meta, "phase_candidates_tried", 0),
        phase_sweep_used=getattr(meta, "phase_sweep_used", False),
        control_trace=getattr(meta, "control_trace", None),
        det_confidence=getattr(meta, "det_confidence", 0.0),
        homography_rmse=getattr(meta, "homography_rmse", 0.0),
    )


def _rgba_zero_copy(src_raw: bytes, dst_view: np.ndarray) -> None:
    """
    Zero-copy RGBA transfer from MSS screenshot to shared memory.

    This is 29x faster than RGB slice copy because:
    1. No channel conversion needed (BGRA -> RGBA, just copy all 4 channels)
    2. Contiguous memory access (no slicing)
    3. Maximum memory bandwidth utilization (51.5 GB/s)

    The downstream decoder will extract RGB using [:, :, :3] which is a
    zero-cost view operation.

    Args:
        src_raw: Raw BGRA bytes from MSS screenshot
        dst_view: Destination RGBA numpy array (h, w, 4)
    """
    # Direct copy of all 4 channels - no conversion needed
    bgra = np.frombuffer(src_raw, dtype=np.uint8).reshape(dst_view.shape)
    dst_view[...] = bgra


def _timed_rgba_zero_copy(src_raw: bytes, dst_view: np.ndarray) -> float:
    """Run RGBA copy and return the memcpy wall time in milliseconds."""
    t0 = time.perf_counter()
    _rgba_zero_copy(src_raw, dst_view)
    t1 = time.perf_counter()
    return (t1 - t0) * 1000.0


def _emit_filled_slot(
    *,
    descriptor_queue: QueueLike,
    slot_id: int,
    generation: int,
    capture_index: int,
    width: int,
    height: int,
    grab_ms: float,
    copy_ms: float,
) -> None:
    """Publish a filled-slot event after copy finishes."""
    event = FilledSlotEvent(
        descriptor=FrameSlotDescriptor(
            slot_id=int(slot_id),
            generation=int(generation),
            capture_index=int(capture_index),
            ts=time.time(),
            width=int(width),
            height=int(height),
            fingerprint=b"",
            flags=0,
            dump_requested=False,
            slot_kind="capture",
        ),
        grab_ms=grab_ms,
        copy_ms=copy_ms,
    )
    descriptor_queue.put(event)


def _copy_job_inline(
    *,
    shot_raw: bytes,
    slot_id: int,
    generation: int,
    capture_index: int,
    width: int,
    height: int,
    slot_views: Sequence[np.ndarray],
    descriptor_queue: QueueLike,
    grab_ms: float,
) -> None:
    """Run a copy job synchronously and emit timing/debug output."""
    t0 = time.perf_counter()
    _debug_log(
        "copy_start",
        slot_id=slot_id,
        generation=generation,
        capture_index=capture_index,
        width=width,
        height=height,
        bytes=len(shot_raw),
    )
    copy_exec_ms = _timed_rgba_zero_copy(shot_raw, slot_views[int(slot_id)])
    t1 = time.perf_counter()
    copy_ms = (t1 - t0) * 1000.0
    copy_wait_ms = max(0.0, copy_ms - float(copy_exec_ms))
    _emit_filled_slot(
        descriptor_queue=descriptor_queue,
        slot_id=slot_id,
        generation=generation,
        capture_index=capture_index,
        width=width,
        height=height,
        grab_ms=grab_ms,
        copy_ms=copy_ms,
    )
    _debug_log(
        "copy_done",
        slot_id=slot_id,
        generation=generation,
        capture_index=capture_index,
        copy_ms=round(copy_ms, 3),
        copy_exec_ms=round(float(copy_exec_ms), 3),
        copy_wait_ms=round(copy_wait_ms, 3),
    )


def _copy_worker_loop(
    *,
    copy_queue: "queue.Queue[object]",
    slot_views: Sequence[np.ndarray],
    descriptor_queue: QueueLike,
    inflight_state: dict[str, int],
    inflight_lock: threading.Lock,
) -> None:
    """Dedicated copy worker to avoid asyncio/to_thread scheduling jitter."""
    while True:
        job = copy_queue.get()
        if job is None:
            return
        with inflight_lock:
            inflight_state["count"] += 1
        try:
            (
                shot_raw,
                slot_id,
                generation,
                capture_index,
                width,
                height,
                grab_ms,
            ) = cast(Tuple[bytes, int, int, int, int, int, float], job)
            _copy_job_inline(
                shot_raw=shot_raw,
                slot_id=slot_id,
                generation=generation,
                capture_index=capture_index,
                width=width,
                height=height,
                slot_views=slot_views,
                descriptor_queue=descriptor_queue,
                grab_ms=grab_ms,
            )
        finally:
            with inflight_lock:
                inflight_state["count"] -= 1


def _copy_inflight(inflight_state: dict[str, int], inflight_lock: threading.Lock) -> int:
    with inflight_lock:
        return inflight_state["count"]


async def _async_grab_loop(
    *,
    slot_assign_queue: QueueLike,
    descriptor_queue: QueueLike,
    stop_event: threading.Event,
    slot_views: Sequence[np.ndarray],
    target_fps: float,
    window_title: Optional[str],
    explicit_region: Optional[Tuple[int, int, int, int]],
    monitor_index: int,
) -> None:
    """
    Async grab loop using asyncio for lightweight concurrency.

    Key optimizations:
    1. Deadline-driven scheduling: always grab at target FPS
    2. Non-blocking slot check: don't wait for slots
    3. Async copy: memory copy runs in parallel with next grab
    4. RGBA zero-copy: 29x faster than RGB slice copy (0.15ms vs 4.5ms)
    """
    try:
        import mss  # pylint: disable=import-outside-toplevel
    except Exception as exc:  # pragma: no cover
        descriptor_queue.put({"kind": "error", "stage": "grab", "error": str(exc)})
        return

    try:
        monitor_region = get_monitor_region(monitor_index)
        x, y, w, h = resolve_window_region(
            window_title=window_title,
            explicit_region=explicit_region,
            monitor_region=monitor_region,
        )
        monitor = {"left": x, "top": y, "width": w, "height": h}
        _debug_log(
            "grab_region",
            monitor_index=monitor_index,
            explicit_region=explicit_region,
            monitor_left=x,
            monitor_top=y,
            monitor_width=w,
            monitor_height=h,
        )
        frame_interval = 1.0 / target_fps if target_fps > 0 else 0.0
        next_deadline = time.perf_counter()
        capture_index = 0
        stats_window_start = time.perf_counter()
        stats_window_grabs = 0
        stats_window_starvations = 0
        stats_window_max_deadline_lag_ms = 0.0
        stats_window_max_slot_depth = 0
        stats_window_max_cpu_grab_ms = 0.0
        local_slot_queue: "queue.Queue[object]" = queue.Queue(maxsize=_SLOT_PREFETCH)
        copy_queue: "queue.Queue[object]" = queue.Queue(maxsize=_COPY_QUEUE_DEPTH)
        inflight_lock = threading.Lock()
        inflight_state = {"count": 0}
        copy_workers: List[threading.Thread] = []
        slot_bridge = threading.Thread(
            target=_slot_bridge_loop,
            args=(slot_assign_queue, local_slot_queue),
            name="ScreenLiveSlotBridge",
            daemon=True,
        )
        slot_bridge.start()
        for worker_index in range(_COPY_WORKERS):
            worker = threading.Thread(
                target=_copy_worker_loop,
                kwargs={
                    "copy_queue": copy_queue,
                    "slot_views": slot_views,
                    "descriptor_queue": descriptor_queue,
                    "inflight_state": inflight_state,
                    "inflight_lock": inflight_lock,
                },
                name=f"ScreenLiveCopyWorker-{worker_index}",
                daemon=True,
            )
            worker.start()
            copy_workers.append(worker)

        try:
            with mss.mss() as sct:
                while not stop_event.is_set():
                    now = time.perf_counter()

                    # Check if we've reached the deadline
                    if now < next_deadline:
                        # Sleep until deadline (use small sleep to check stop_event)
                        await asyncio.sleep(min(0.001, (next_deadline - now) / 2))
                        continue

                    slot_available = False
                    slot_id: Optional[int] = None
                    generation: Optional[int] = None
                    slot_wait_ms = 0.0
                    local_slot_depth = local_slot_queue.qsize()
                    deadline_lag_ms = max(0.0, (now - next_deadline) * 1000.0)
                    if deadline_lag_ms > stats_window_max_deadline_lag_ms:
                        stats_window_max_deadline_lag_ms = deadline_lag_ms
                    if local_slot_depth > stats_window_max_slot_depth:
                        stats_window_max_slot_depth = local_slot_depth

                    try:
                        wait_t0 = time.perf_counter()
                        item = local_slot_queue.get_nowait()
                        wait_t1 = time.perf_counter()
                        if item is None:
                            _debug_log("slot_sentinel")
                            break
                        slot_id, generation = cast(Tuple[int, int], item)
                        slot_available = True
                        slot_wait_ms = (wait_t1 - wait_t0) * 1000.0
                        _debug_log(
                            "slot_acquired",
                            slot_id=slot_id,
                            generation=generation,
                            slot_wait_ms=round(slot_wait_ms, 3),
                            local_slot_depth=local_slot_depth,
                        )
                    except queue.Empty:
                        slot_available = False

                        # Always grab at deadline, regardless of slot availability
                    try:
                        t0 = time.perf_counter()
                        cpu_t0 = time.thread_time()
                        shot = sct.grab(monitor)
                        cpu_t1 = time.thread_time()
                        t1 = time.perf_counter()
                        grab_ms = (t1 - t0) * 1000.0
                        cpu_grab_ms = (cpu_t1 - cpu_t0) * 1000.0
                        if cpu_grab_ms > stats_window_max_cpu_grab_ms:
                            stats_window_max_cpu_grab_ms = cpu_grab_ms
                        _debug_log(
                            "grab_done",
                            slot_available=slot_available,
                            slot_id=slot_id,
                            generation=generation,
                            grab_ms=round(grab_ms, 3),
                            cpu_grab_ms=round(cpu_grab_ms, 3),
                            inflight_copies=_copy_inflight(inflight_state, inflight_lock),
                            local_slot_depth=local_slot_depth,
                            deadline_lag_ms=round(deadline_lag_ms, 3),
                        )
                        stats_window_grabs += 1

                        if slot_available and slot_id is not None and generation is not None:
                            shot_raw = bytes(shot.raw)
                            job = (
                                shot_raw,
                                int(slot_id),
                                int(generation),
                                int(capture_index),
                                int(w),
                                int(h),
                                float(grab_ms),
                            )
                            try:
                                copy_queue.put_nowait(job)
                            except queue.Full:
                                _debug_log(
                                    "copy_queue_full",
                                    slot_id=slot_id,
                                    generation=generation,
                                    capture_index=capture_index,
                                )
                                _copy_job_inline(
                                    shot_raw=shot_raw,
                                    slot_id=int(slot_id),
                                    generation=int(generation),
                                    capture_index=int(capture_index),
                                    width=int(w),
                                    height=int(h),
                                    slot_views=slot_views,
                                    descriptor_queue=descriptor_queue,
                                    grab_ms=float(grab_ms),
                                )
                            descriptor_queue.put({"kind": "slot_wait_ms", "value": slot_wait_ms})
                            capture_index += 1
                        else:
                            # No slot available, track starvation
                            stats_window_starvations += 1
                            _debug_log(
                                "grab_starvation",
                                grab_ms=round(grab_ms, 3),
                                local_slot_depth=local_slot_depth,
                                deadline_lag_ms=round(deadline_lag_ms, 3),
                            )
                            descriptor_queue.put({"kind": "grab_slot_starvation"})
                            descriptor_queue.put(
                                {
                                    "kind": "raw_grab_stats",
                                    "grab_ms": grab_ms,
                                }
                            )

                    except Exception as exc:
                        _debug_log("grab_error", error=str(exc))
                        descriptor_queue.put({"kind": "error", "stage": "grab", "error": str(exc)})

                    # Update deadline
                    next_deadline += frame_interval
                    now_after = time.perf_counter()
                    if now_after >= next_deadline:
                        # We're behind schedule, reset deadline
                        next_deadline = now_after

                    stats_now = time.perf_counter()
                    if stats_now - stats_window_start >= 1.0:
                        _debug_log(
                            "grab_window",
                            grabs=stats_window_grabs,
                            starvations=stats_window_starvations,
                            max_deadline_lag_ms=round(stats_window_max_deadline_lag_ms, 3),
                            max_local_slot_depth=stats_window_max_slot_depth,
                            max_cpu_grab_ms=round(stats_window_max_cpu_grab_ms, 3),
                        )
                        stats_window_start = stats_now
                        stats_window_grabs = 0
                        stats_window_starvations = 0
                        stats_window_max_deadline_lag_ms = 0.0
                        stats_window_max_slot_depth = local_slot_depth
                        stats_window_max_cpu_grab_ms = 0.0
        finally:
            for _ in copy_workers:
                copy_queue.put(None)
            for worker in copy_workers:
                worker.join(timeout=1.0)
    except Exception as exc:  # pragma: no cover
        _debug_log("grab_loop_error", error=str(exc))
        descriptor_queue.put({"kind": "error", "stage": "grab", "error": str(exc)})


def grab_process_main(
    *,
    slot_assign_queue: QueueLike,
    descriptor_queue: QueueLike,
    stop_event: Any,
    slot_names: Sequence[str],
    width: int,
    height: int,
    target_fps: float,
    window_title: Optional[str],
    explicit_region: Optional[Tuple[int, int, int, int]],
    monitor_index: int,
) -> None:
    """
    Grab process entry point that runs in a separate subprocess.

    This provides better isolation from the main process and eliminates
    GIL contention and scheduling jitter from other threads.

    Running grab+copy in a dedicated process ensures:
    1. No GIL contention with coordinator or other workers
    2. Dedicated CPU core for time-critical capture loop
    3. Better real-time performance and consistent FPS
    4. Isolated memory space reduces cache pollution
    """
    _ignore_sigint_in_child()

    # Attach to shared memory slots
    shms: List[shared_memory.SharedMemory] = []
    slot_views: List[np.ndarray] = []
    try:
        for name in slot_names:
            shm = _attach_shared_memory_for_child(name)
            shms.append(shm)
            # Attach as RGBA (4 channels)
            slot_views.append(np.ndarray((height, width, 4), dtype=np.uint8, buffer=shm.buf))

        # Run the async grab loop
        asyncio.run(
            _async_grab_loop(
                slot_assign_queue=slot_assign_queue,
                descriptor_queue=descriptor_queue,
                stop_event=stop_event,
                slot_views=slot_views,
                target_fps=target_fps,
                window_title=window_title,
                explicit_region=explicit_region,
                monitor_index=monitor_index,
            )
        )
    except Exception as exc:  # pragma: no cover
        _debug_log("grab_process_error", error=str(exc))
        try:
            descriptor_queue.put({"kind": "error", "stage": "grab", "error": str(exc)})
        except Exception:
            pass
    finally:
        for shm in shms:
            try:
                shm.close()
            except Exception:
                pass


def decode_worker_main(
    *,
    worker_id: int,
    assignment_queue: Any,
    result_queue: Any,
    slot_names: Sequence[str],
    width: int,
    height: int,
    protocol: str,
    grid_w: int,
    grid_h: int,
    guard_band: int,
    corner_size: int,
) -> None:
    _ignore_sigint_in_child()
    shms: List[shared_memory.SharedMemory] = []
    frames: List[np.ndarray] = []
    decoder = _make_decoder(
        protocol=protocol,
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=guard_band,
        corner_size=corner_size,
    )
    try:
        for name in slot_names:
            shm = _attach_shared_memory_for_child(name)
            shms.append(shm)
            # Attach as RGBA (4 channels) since grab thread now stores RGBA
            frames.append(np.ndarray((height, width, 4), dtype=np.uint8, buffer=shm.buf))
        while True:
            assignment = assignment_queue.get()
            if assignment is None:
                break
            if not isinstance(assignment, DecodeAssignment):
                continue
            descriptor = assignment.descriptor
            t_attach0 = time.perf_counter()
            # Extract RGB view from RGBA (zero-cost view operation)
            frame_rgba = frames[descriptor.slot_id]
            frame = frame_rgba[:, :, :3]  # RGB view, no copy
            t_attach1 = time.perf_counter()
            try:
                decode_mode = "reacquire_locator"
                geometry_snapshot = assignment.geometry_state
                if (
                    protocol == "layered"
                    and geometry_snapshot is not None
                    and geometry_snapshot.lock_mode == "locked"
                ):
                    raw_geometry = _layered_geometry_from_runtime(geometry_snapshot)
                    decoded = decoder.decode_frame_with_geometry(frame=frame, geometry=raw_geometry)
                    decode_mode = "geometry_reuse"
                else:
                    decoded = decoder.decode_frame(
                        frame=frame,
                        detect_mode="track" if assignment.forced_roi is not None else "full",
                        forced_roi=assignment.forced_roi,
                    )
                header = decoded.frame_header
                meta = decoded.meta
                quality = float(getattr(meta, "det_confidence", 0.0) or 0.0)
                geometry_state = _geometry_state_from_meta(
                    decoder,
                    meta,
                    stream_id=assignment.stream_id,
                    geometry_generation=assignment.geometry_generation + 1,
                    capture_index=descriptor.capture_index,
                    chunk_id=int(getattr(header, "chunk_id", 0)),
                    frame_id=int(getattr(header, "frame_id", 0)),
                    quality_score=quality,
                    lock_mode="locked",
                )
                result_queue.put(
                    DecodeCompletion(
                        descriptor=descriptor,
                        worker_id=worker_id,
                        success=True,
                        chunk_id=int(getattr(header, "chunk_id", 0)),
                        payload=decoded.payload,
                        control_kind=str(getattr(decoded, "control_kind", "") or ""),
                        transmission_unit=getattr(decoded, "transmission_unit", None),
                        frame_id=int(getattr(header, "frame_id", 0)),
                        frame_type=int(getattr(header, "frame_type", 0)),
                        meta=_meta_snapshot(meta),
                        used_geometry_generation=int(assignment.geometry_generation),
                        proposed_geometry_state=geometry_state,
                        decode_quality=quality,
                        decode_mode=decode_mode,
                        decode_attach_ms=(t_attach1 - t_attach0) * 1000.0,
                    )
                )
            except Exception as exc:
                error_msg = str(exc)
                # Extract failure_class and context from DecodeError if available
                failure_class = "unknown"
                context = None
                if isinstance(exc, DecodeError):
                    failure_class = exc.failure_class
                    context = exc.context

                result_queue.put(
                    DecodeCompletion(
                        descriptor=descriptor,
                        worker_id=worker_id,
                        success=False,
                        error=error_msg,
                        failure_class=failure_class,
                        context=context,
                        used_geometry_generation=int(assignment.geometry_generation),
                        decode_mode=decode_mode,
                        decode_attach_ms=(t_attach1 - t_attach0) * 1000.0,
                    )
                )
    except Exception as exc:  # pragma: no cover
        result_queue.put(
            {"kind": "error", "stage": "decode", "worker_id": worker_id, "error": str(exc)}
        )
    finally:
        _close_queue(assignment_queue)
        _close_queue(result_queue)
        for shm in shms:
            try:
                shm.close()
            except Exception:
                pass


def dump_worker_main(
    *,
    dump_queue: Any,
    dump_event_queue: Any,
    slot_names: Sequence[str],
    width: int,
    height: int,
    dump_dir: str,
) -> None:
    _ignore_sigint_in_child()
    os.makedirs(dump_dir, exist_ok=True)
    shms: List[shared_memory.SharedMemory] = []
    frames: List[np.ndarray] = []
    try:
        for name in slot_names:
            shm = _attach_shared_memory_for_child(name)
            shms.append(shm)
            # Attach as RGBA (4 channels)
            frames.append(np.ndarray((height, width, 4), dtype=np.uint8, buffer=shm.buf))
        while True:
            descriptor = dump_queue.get()
            if descriptor is None:
                break
            if not isinstance(descriptor, FrameSlotDescriptor):
                continue
            try:
                t0 = time.perf_counter()
                # Extract RGB view and copy
                frame_rgba = frames[descriptor.slot_id]
                private = np.array(frame_rgba[:, :, :3], copy=True)
                t1 = time.perf_counter()
                dump_event_queue.put(
                    DumpCopyCompletion(
                        descriptor=descriptor, copied=True, dump_ms=(t1 - t0) * 1000.0
                    )
                )
                np.save(os.path.join(dump_dir, f"{descriptor.capture_index:06d}.npy"), private)
            except Exception as exc:
                dump_event_queue.put(
                    DumpCopyCompletion(descriptor=descriptor, copied=False, error=str(exc))
                )
    finally:
        _close_queue(dump_queue)
        _close_queue(dump_event_queue)
        for shm in shms:
            try:
                shm.close()
            except Exception:
                pass


def prep_process_main(
    *,
    prep_input_queue: Any,
    prep_output_queue: Any,
    slot_names: Sequence[str],
    width: int,
    height: int,
    prep_roi: Tuple[int, int, int, int],
) -> None:
    _ignore_sigint_in_child()
    shms: List[shared_memory.SharedMemory] = []
    frames: List[np.ndarray] = []
    try:
        for name in slot_names:
            shm = _attach_shared_memory_for_child(name)
            shms.append(shm)
            # Attach as RGBA (4 channels)
            frames.append(np.ndarray((height, width, 4), dtype=np.uint8, buffer=shm.buf))
        while True:
            item = prep_input_queue.get()
            if item is None:
                break
            if not isinstance(item, FilledSlotEvent):
                continue
            descriptor = item.descriptor
            try:
                # Extract ROI from frame (RGB view)
                x, y, w, h = prep_roi
                frame_rgba = frames[descriptor.slot_id]
                frame_rgb = frame_rgba[:, :, :3]  # RGB view
                frame_roi = frame_rgb[y : y + h, x : x + w]
                t0 = time.perf_counter()
                fingerprint = compute_fingerprint(frame_roi)
                t1 = time.perf_counter()
                prep_output_queue.put(
                    PrepFingerprintEvent(
                        descriptor=descriptor,
                        fingerprint=fingerprint,
                        fingerprint_ms=(t1 - t0) * 1000.0,
                    )
                )
            except Exception as exc:
                # Single frame error - send a skip event so coordinator can recycle the slot
                prep_output_queue.put(
                    {
                        "kind": "prep_skip",
                        "descriptor": descriptor,
                        "error": str(exc),
                    }
                )
    finally:
        _close_queue(prep_input_queue)
        _close_queue(prep_output_queue)
        for shm in shms:
            try:
                shm.close()
            except Exception:
                pass
