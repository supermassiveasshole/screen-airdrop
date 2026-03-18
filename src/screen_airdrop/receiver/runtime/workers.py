"""Worker process entry points and helper functions."""

import asyncio
import os
import queue
import signal
import threading
import time
from multiprocessing import shared_memory
from types import SimpleNamespace
from typing import Any, List, Optional, Protocol, Sequence, Tuple, cast

import numpy as np

from screen_airdrop.receiver.capture_mss import get_monitor_region
from screen_airdrop.receiver.decode_errors import DecodeError
from screen_airdrop.receiver.protocol_decoder_factory import create_protocol_decoder
from screen_airdrop.receiver.runtime.events import (
    DecodeAssignment,
    DecodeCompletion,
    DumpCopyCompletion,
    FilledSlotEvent,
    FrameSlotDescriptor,
    PrepFingerprintEvent,
)
from screen_airdrop.receiver.runtime.frame_preprocessor import compute_fingerprint
from screen_airdrop.receiver.runtime.geometry_tracker import GeometryState
from screen_airdrop.receiver.window_locator import resolve_window_region


class QueueLike(Protocol):
    """Protocol for queue-like objects."""

    def get(self) -> object: ...
    def put(self, item: object) -> object: ...


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
    from screen_airdrop.receiver.decoder_layered import LayeredGeometryState

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
        mask_id=getattr(meta, "mask_id", -1),
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


async def _async_copy_task(
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
    """
    Async copy task that runs in thread pool.

    This allows the grab loop to continue immediately after capture
    without waiting for the memory copy to complete.
    """
    t0 = time.perf_counter()

    # Run the memory copy in a thread pool to avoid blocking the event loop
    await asyncio.to_thread(_rgba_zero_copy, shot_raw, slot_views[int(slot_id)])

    t1 = time.perf_counter()
    copy_ms = (t1 - t0) * 1000.0

    # Send completion event
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
        frame_interval = 1.0 / target_fps if target_fps > 0 else 0.0
        next_deadline = time.perf_counter()
        capture_index = 0

        with mss.mss() as sct:
            while not stop_event.is_set():
                now = time.perf_counter()

                # Check if we've reached the deadline
                if now < next_deadline:
                    # Sleep until deadline (use small sleep to check stop_event)
                    await asyncio.sleep(min(0.001, (next_deadline - now) / 2))
                    continue

                # Try to get a slot (non-blocking)
                slot_available = False
                slot_id: Optional[int] = None
                generation: Optional[int] = None

                try:
                    wait_t0 = time.perf_counter()
                    item = slot_assign_queue.get()  # type: ignore[call-arg]
                    wait_t1 = time.perf_counter()
                    if item is None:
                        break
                    slot_id, generation = cast(Tuple[int, int], item)
                    slot_available = True
                    slot_wait_ms = (wait_t1 - wait_t0) * 1000.0
                except queue.Empty:
                    slot_available = False

                # Always grab at deadline, regardless of slot availability
                try:
                    t0 = time.perf_counter()
                    shot = sct.grab(monitor)
                    t1 = time.perf_counter()
                    grab_ms = (t1 - t0) * 1000.0

                    if slot_available and slot_id is not None and generation is not None:
                        # We have a slot, start async copy
                        # Convert shot to bytes for thread-safe passing
                        shot_raw = bytes(shot.raw)

                        # Create async copy task (non-blocking)
                        asyncio.create_task(
                            _async_copy_task(
                                shot_raw=shot_raw,
                                slot_id=slot_id,
                                generation=generation,
                                capture_index=capture_index,
                                width=w,
                                height=h,
                                slot_views=slot_views,
                                descriptor_queue=descriptor_queue,
                                grab_ms=grab_ms,
                            )
                        )

                        descriptor_queue.put({"kind": "slot_wait_ms", "value": slot_wait_ms})
                        capture_index += 1
                    else:
                        # No slot available, track starvation
                        descriptor_queue.put({"kind": "grab_slot_starvation"})
                        descriptor_queue.put(
                            {
                                "kind": "raw_grab_stats",
                                "grab_ms": grab_ms,
                            }
                        )

                except Exception as exc:
                    descriptor_queue.put({"kind": "error", "stage": "grab", "error": str(exc)})

                # Update deadline
                next_deadline += frame_interval
                now_after = time.perf_counter()
                if now_after >= next_deadline:
                    # We're behind schedule, reset deadline
                    next_deadline = now_after

    except Exception as exc:  # pragma: no cover
        descriptor_queue.put({"kind": "error", "stage": "grab", "error": str(exc)})


def _grab_process_main(
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
    finally:
        for shm in shms:
            try:
                shm.close()
            except Exception:
                pass


def _decode_worker_main(
    *,
    worker_id: int,
    assignment_queue: Any,
    result_queue: Any,
    stop_event: Any,
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
            time.perf_counter()
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


def _dump_worker_main(
    *,
    dump_queue: Any,
    dump_event_queue: Any,
    stop_event: Any,
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


def _prep_process_main(
    *,
    prep_input_queue: Any,
    prep_output_queue: Any,
    stop_event: Any,
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
