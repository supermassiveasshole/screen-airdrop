"""Worker process entry points and helper functions."""

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
    if state is None or state.quad_src is None or state.homography is None or state.homography_inv is None:
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


def _grab_process_main(
    *,
    slot_assign_queue: Any,
    descriptor_queue: Any,
    stop_event: Any,
    slot_names: Sequence[str],
    width: int,
    height: int,
    target_fps: float,
    window_title: Optional[str],
    explicit_region: Optional[Tuple[int, int, int, int]],
    monitor_index: int,
) -> None:
    _ignore_sigint_in_child()
    try:
        import mss  # pylint: disable=import-outside-toplevel
    except Exception as exc:  # pragma: no cover
        descriptor_queue.put({"kind": "error", "stage": "grab", "error": str(exc)})
        return
    shms: List[shared_memory.SharedMemory] = []
    slots: List[np.ndarray] = []
    try:
        for name in slot_names:
            shm = _attach_shared_memory_for_child(name)
            shms.append(shm)
            slots.append(np.ndarray((height, width, 3), dtype=np.uint8, buffer=shm.buf))
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
            while True:
                wait_t0 = time.perf_counter()
                item = slot_assign_queue.get()
                if item is None:
                    break
                slot_id, generation = cast(Tuple[int, int], item)
                slot_wait_ms = (time.perf_counter() - wait_t0) * 1000.0
                t0 = time.perf_counter()
                shot = sct.grab(monitor)
                t1 = time.perf_counter()
                bgra = np.asarray(shot)
                slots[slot_id][...] = bgra[:, :, :3]
                descriptor_queue.put(
                    FilledSlotEvent(
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
                        grab_ms=(t1 - t0) * 1000.0,
                    )
                )
                descriptor_queue.put({"kind": "slot_wait_ms", "value": slot_wait_ms})
                capture_index += 1
                if frame_interval > 0:
                    next_deadline += frame_interval
                    now = time.perf_counter()
                    if now < next_deadline:
                        time.sleep(next_deadline - now)
                    elif now - next_deadline > frame_interval:
                        next_deadline = now + frame_interval
    except Exception as exc:  # pragma: no cover
        descriptor_queue.put({"kind": "error", "stage": "grab", "error": str(exc)})
    finally:
        _close_queue(slot_assign_queue)
        _close_queue(descriptor_queue)
        for shm in shms:
            try:
                shm.close()
            except Exception:
                pass


def _grab_thread_main(
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
                # Wait for slot assignment
                wait_t0 = time.perf_counter()
                try:
                    # Use non-blocking get to check for slot immediately
                    item = slot_assign_queue.get(block=False)
                except queue.Empty:
                    # No slot available right now
                    # Check if we should grab anyway (to maintain raw_grab_fps)
                    now = time.perf_counter()
                    if now >= next_deadline:
                        # Time to grab, even without slot
                        try:
                            t0 = time.perf_counter()
                            shot = sct.grab(monitor)
                            t1 = time.perf_counter()
                            grab_ms = (t1 - t0) * 1000.0

                            descriptor_queue.put({"kind": "grab_slot_starvation"})
                            descriptor_queue.put({
                                "kind": "raw_grab_stats",
                                "grab_ms": grab_ms,
                            })
                        except Exception:
                            pass

                        # Update deadline
                        next_deadline += frame_interval
                        if now - next_deadline > frame_interval:
                            next_deadline = now + frame_interval
                    else:
                        # Not time to grab yet, sleep a bit and retry
                        time.sleep(0.001)
                    continue

                if item is None:
                    break

                slot_id, generation = cast(Tuple[int, int], item)
                slot_wait_ms = (time.perf_counter() - wait_t0) * 1000.0

                # Now we have a slot, grab the frame
                try:
                    t0 = time.perf_counter()
                    shot = sct.grab(monitor)
                    t1 = time.perf_counter()
                    grab_ms = (t1 - t0) * 1000.0

                    # Copy to slot
                    bgra = np.asarray(shot)
                    slot_views[int(slot_id)][...] = bgra[:, :, :3]
                    t2 = time.perf_counter()
                    copy_ms = (t2 - t1) * 1000.0

                    event = FilledSlotEvent(
                        descriptor=FrameSlotDescriptor(
                            slot_id=int(slot_id),
                            generation=int(generation),
                            capture_index=int(capture_index),
                            ts=time.time(),
                            width=int(w),
                            height=int(h),
                            fingerprint=b"",
                            flags=0,
                            dump_requested=False,
                            slot_kind="capture",
                        ),
                        grab_ms=grab_ms,
                        copy_ms=copy_ms,
                    )
                    descriptor_queue.put(event)
                    descriptor_queue.put({"kind": "slot_wait_ms", "value": slot_wait_ms})
                except Exception as exc:
                    descriptor_queue.put({"kind": "error", "stage": "grab", "error": str(exc)})

                capture_index += 1

                # Sleep to maintain target FPS
                if frame_interval > 0:
                    next_deadline += frame_interval
                    now = time.perf_counter()
                    if now < next_deadline:
                        time.sleep(next_deadline - now)
                    elif now - next_deadline > frame_interval:
                        next_deadline = now + frame_interval
    except Exception as exc:  # pragma: no cover
        descriptor_queue.put({"kind": "error", "stage": "grab", "error": str(exc)})


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
            frames.append(np.ndarray((height, width, 3), dtype=np.uint8, buffer=shm.buf))
        while True:
            assignment = assignment_queue.get()
            if assignment is None:
                break
            if not isinstance(assignment, DecodeAssignment):
                continue
            descriptor = assignment.descriptor
            t_attach0 = time.perf_counter()
            frame = frames[descriptor.slot_id]
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
        result_queue.put({"kind": "error", "stage": "decode", "worker_id": worker_id, "error": str(exc)})
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
            frames.append(np.ndarray((height, width, 3), dtype=np.uint8, buffer=shm.buf))
        while True:
            descriptor = dump_queue.get()
            if descriptor is None:
                break
            if not isinstance(descriptor, FrameSlotDescriptor):
                continue
            try:
                t0 = time.perf_counter()
                private = np.array(frames[descriptor.slot_id], copy=True)
                t1 = time.perf_counter()
                dump_event_queue.put(
                    DumpCopyCompletion(descriptor=descriptor, copied=True, dump_ms=(t1 - t0) * 1000.0)
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
            frames.append(np.ndarray((height, width, 3), dtype=np.uint8, buffer=shm.buf))
        while True:
            item = prep_input_queue.get()
            if item is None:
                break
            if not isinstance(item, FilledSlotEvent):
                continue
            descriptor = item.descriptor
            try:
                # Extract ROI from frame
                x, y, w, h = prep_roi
                frame_roi = frames[descriptor.slot_id][y : y + h, x : x + w]
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
                prep_output_queue.put({
                    "kind": "prep_skip",
                    "descriptor": descriptor,
                    "error": str(exc),
                })
    finally:
        _close_queue(prep_input_queue)
        _close_queue(prep_output_queue)
        for shm in shms:
            try:
                shm.close()
            except Exception:
                pass


