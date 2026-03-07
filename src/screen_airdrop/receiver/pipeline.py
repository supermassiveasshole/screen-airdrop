"""Async capture-decode pipeline using producer-consumer threads."""

from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple, Union

import numpy as np

from screen_airdrop.common.protocol_basic import DEFAULT_GRID_H, DEFAULT_GRID_W, FRAME_DATA
from screen_airdrop.receiver.assembler import ChunkAssembler
from screen_airdrop.receiver.capture_mss import compute_frame_diff, screenshot_to_bgr
from screen_airdrop.receiver.decoder_basic import DecodeMetaBasic, decode_frame_basic


@dataclass
class DecodeResult:
    chunk_id: int
    payload: bytes
    frame_id: int
    frame_type: int
    meta: DecodeMetaBasic


@dataclass
class PipelineStats:
    captured: int = 0
    dropped_queue_full: int = 0
    duplicate_frames: int = 0
    decode_ok: int = 0
    decode_fail: int = 0
    decode_exceptions: int = 0
    dropped_result_queue_full: int = 0
    assembled: int = 0
    assembled_bytes: int = 0
    capture_grab_time_ms: float = 0.0
    capture_copy_time_ms: float = 0.0
    capture_dedup_time_ms: float = 0.0
    capture_grab_ops: int = 0
    capture_copy_ops: int = 0
    capture_dedup_ops: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> Dict[str, Union[int, float]]:
        with self._lock:
            return {
                "captured": self.captured,
                "dropped_queue_full": self.dropped_queue_full,
                "duplicate_frames": self.duplicate_frames,
                "decode_ok": self.decode_ok,
                "decode_fail": self.decode_fail,
                "decode_exceptions": self.decode_exceptions,
                "dropped_result_queue_full": self.dropped_result_queue_full,
                "assembled": self.assembled,
                "assembled_bytes": self.assembled_bytes,
                "capture_grab_time_ms": self.capture_grab_time_ms,
                "capture_copy_time_ms": self.capture_copy_time_ms,
                "capture_dedup_time_ms": self.capture_dedup_time_ms,
                "capture_grab_ops": self.capture_grab_ops,
                "capture_copy_ops": self.capture_copy_ops,
                "capture_dedup_ops": self.capture_dedup_ops,
            }


class CaptureThread(threading.Thread):
    """Grabs frames from a ScreenCapture source and pushes into frame_queue."""

    def __init__(
        self,
        capture,  # ScreenCapture instance
        frame_queue: queue.Queue,
        stop_event: threading.Event,
        stats: PipelineStats,
        frame_diff_threshold: float = 0.015,
        target_fps: float = 30.0,
    ) -> None:
        super().__init__(daemon=True, name="CaptureThread")
        self._capture = capture
        self._frame_queue = frame_queue
        self._stop_ev = stop_event
        self._stats = stats
        self._frame_diff_threshold = frame_diff_threshold
        self._target_fps = target_fps
        self.error: Optional[Exception] = None

    def run(self) -> None:
        try:
            self._run_loop()
        except Exception as exc:
            self.error = exc

    def _run_loop(self) -> None:
        mss_mod = self._capture._mss_mod
        from screen_airdrop.receiver.capture_mss import get_monitor_region
        from screen_airdrop.receiver.window_locator import resolve_window_region

        monitor_region = get_monitor_region(self._capture.monitor_index)
        x, y, w, h = resolve_window_region(
            window_title=self._capture.window_title,
            explicit_region=self._capture.region,
            monitor_region=monitor_region,
        )
        self._capture.active_region = (x, y, w, h)
        monitor = {"left": x, "top": y, "width": w, "height": h}

        frame_interval = 1.0 / self._target_fps if self._target_fps > 0 else 0.0
        prev_frame: Optional[np.ndarray] = None
        last_grab = time.perf_counter()

        with mss_mod.mss() as sct:
            while not self._stop_ev.is_set():
                t0 = time.perf_counter()
                shot = sct.grab(monitor)
                t1 = time.perf_counter()
                frame = screenshot_to_bgr(shot)
                t2 = time.perf_counter()

                with self._stats._lock:
                    self._stats.captured += 1
                    self._stats.capture_grab_time_ms += (t1 - t0) * 1000.0
                    self._stats.capture_copy_time_ms += (t2 - t1) * 1000.0
                    self._stats.capture_grab_ops += 1
                    self._stats.capture_copy_ops += 1

                # Frame difference dedup
                if prev_frame is not None:
                    t3 = time.perf_counter()
                    diff = compute_frame_diff(frame, prev_frame)
                    t4 = time.perf_counter()
                    with self._stats._lock:
                        self._stats.capture_dedup_time_ms += (t4 - t3) * 1000.0
                        self._stats.capture_dedup_ops += 1
                    if diff < self._frame_diff_threshold:
                        with self._stats._lock:
                            self._stats.duplicate_frames += 1
                        time.sleep(0.004)
                        continue

                prev_frame = frame

                # Rate limiting
                now = time.perf_counter()
                if frame_interval > 0:
                    elapsed = now - last_grab
                    if elapsed < frame_interval:
                        time.sleep(frame_interval - elapsed)
                last_grab = time.perf_counter()

                # Push to queue; if full, drop the oldest frame to keep freshness
                if self._frame_queue.full():
                    try:
                        self._frame_queue.get_nowait()
                        with self._stats._lock:
                            self._stats.dropped_queue_full += 1
                    except queue.Empty:
                        pass
                try:
                    self._frame_queue.put_nowait(frame)
                except queue.Full:
                    with self._stats._lock:
                        self._stats.dropped_queue_full += 1


class DecodeWorker(threading.Thread):
    """Pops frames from frame_queue, decodes, pushes DecodeResult into result_queue."""

    def __init__(
        self,
        worker_id: int,
        frame_queue: queue.Queue,
        result_queue: queue.Queue,
        stop_event: threading.Event,
        stats: PipelineStats,
        grid_w: int = DEFAULT_GRID_W,
        grid_h: int = DEFAULT_GRID_H,
        guard_band: int = 2,
        corner_size: int = 9,
        locator_engine: str = "auto",
        locator_confidence_threshold: float = 0.55,
        initial_search_roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> None:
        super().__init__(daemon=True, name="DecodeWorker-{0}".format(worker_id))
        self._worker_id = worker_id
        self._frame_queue = frame_queue
        self._result_queue = result_queue
        self._stop_ev = stop_event
        self._stats = stats
        self._grid_w = grid_w
        self._grid_h = grid_h
        self._guard_band = guard_band
        self._corner_size = corner_size
        self._locator_engine = locator_engine
        self._locator_confidence_threshold = locator_confidence_threshold
        # Per-worker track ROI state. Keep user-provided seed ROI as failure fallback.
        self._initial_search_roi = initial_search_roi
        self._track_roi: Optional[Tuple[int, int, int, int]] = initial_search_roi
        self.error: Optional[Exception] = None

    def run(self) -> None:
        try:
            self._run_loop()
        except Exception as exc:
            self.error = exc

    def _run_loop(self) -> None:
        while not self._stop_ev.is_set():
            try:
                frame = self._frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                search_roi = self._track_roi
                detect_mode = "track" if search_roi is not None else "full"
                header, payload, meta = decode_frame_basic(
                    frame=frame,
                    detect_mode=detect_mode,
                    forced_roi=search_roi,
                    grid_w=self._grid_w,
                    grid_h=self._grid_h,
                    guard_band=self._guard_band,
                    corner_size=self._corner_size,
                    locator_engine=self._locator_engine,
                    locator_confidence_threshold=self._locator_confidence_threshold,
                )
                # Update per-worker track ROI from successful decode
                bx, by, bw, bh = meta.det_bbox
                fh, fw = frame.shape[:2]
                margin = max(24, min(96, int(min(bw, bh) * 0.10)))
                x1 = max(0, bx - margin)
                y1 = max(0, by - margin)
                x2 = min(fw, bx + bw + margin)
                y2 = min(fh, by + bh + margin)
                self._track_roi = (x1, y1, x2 - x1, y2 - y1)

                result = DecodeResult(
                    chunk_id=int(header.chunk_id),
                    payload=payload,
                    frame_id=int(header.frame_id),
                    frame_type=int(header.frame_type),
                    meta=meta,
                )
                try:
                    self._result_queue.put(result, timeout=1.0)
                    with self._stats._lock:
                        self._stats.decode_ok += 1
                except queue.Full:
                    with self._stats._lock:
                        self._stats.dropped_result_queue_full += 1
            except Exception:
                self._track_roi = self._initial_search_roi
                with self._stats._lock:
                    self._stats.decode_fail += 1
                    self._stats.decode_exceptions += 1


class AssemblerThread(threading.Thread):
    """Pops DecodeResults, feeds ChunkAssembler, signals done_event on completion."""

    def __init__(
        self,
        result_queue: queue.Queue,
        assembler: ChunkAssembler,
        done_event: threading.Event,
        stop_event: threading.Event,
        stats: PipelineStats,
        on_frame_callback: Optional[Any] = None,
    ) -> None:
        super().__init__(daemon=True, name="AssemblerThread")
        self._result_queue = result_queue
        self._assembler = assembler
        self._done_event = done_event
        self._stop_ev = stop_event
        self._stats = stats
        self._on_frame_callback = on_frame_callback  # callable(result: DecodeResult)
        self.error: Optional[Exception] = None

    def run(self) -> None:
        try:
            self._run_loop()
        except Exception as exc:
            self.error = exc

    def _run_loop(self) -> None:
        while not self._stop_ev.is_set() or not self._result_queue.empty():
            try:
                result = self._result_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if result.frame_type == FRAME_DATA:
                if result.chunk_id > 0:
                    is_new_chunk = result.chunk_id not in self._assembler.chunks
                    self._assembler.add(result.chunk_id, result.payload)
                    if is_new_chunk:
                        with self._stats._lock:
                            self._stats.assembled += 1
                            self._stats.assembled_bytes += len(result.payload)
                elif result.chunk_id == 0:
                    # Manifest is encoded as DATA frame with chunk_id=0.
                    # Ignore malformed manifest payloads instead of crashing the assembler thread.
                    try:
                        self._assembler.add(0, result.payload)
                    except Exception:
                        pass

            if self._on_frame_callback is not None:
                try:
                    self._on_frame_callback(result)
                except Exception:
                    pass

            if self._assembler.complete():
                self._done_event.set()


class ReceiverPipeline:
    """Coordinates CaptureThread, N DecodeWorkers, and AssemblerThread."""

    def __init__(
        self,
        capture,  # ScreenCapture instance
        assembler: ChunkAssembler,
        num_workers: Optional[int] = None,
        capture_fps: float = 30.0,
        frame_diff_threshold: float = 0.015,
        frame_queue_size: int = 32,
        result_queue_size: int = 256,
        grid_w: int = DEFAULT_GRID_W,
        grid_h: int = DEFAULT_GRID_H,
        guard_band: int = 2,
        corner_size: int = 9,
        locator_engine: str = "auto",
        locator_confidence_threshold: float = 0.55,
        on_frame_callback: Optional[Any] = None,
        initial_search_roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> None:
        if num_workers is None:
            num_workers = min(4, max(1, (os.cpu_count() or 2) // 2))
        self._num_workers = num_workers

        self.stats = PipelineStats()
        self._frame_queue: queue.Queue = queue.Queue(maxsize=frame_queue_size)
        self._result_queue: queue.Queue = queue.Queue(maxsize=result_queue_size)
        self._stop_event = threading.Event()
        self.done_event = threading.Event()

        self._capture_thread = CaptureThread(
            capture=capture,
            frame_queue=self._frame_queue,
            stop_event=self._stop_event,
            stats=self.stats,
            frame_diff_threshold=frame_diff_threshold,
            target_fps=capture_fps,
        )
        self._decode_workers = [
            DecodeWorker(
                worker_id=i,
                frame_queue=self._frame_queue,
                result_queue=self._result_queue,
                stop_event=self._stop_event,
                stats=self.stats,
                grid_w=grid_w,
                grid_h=grid_h,
                guard_band=guard_band,
                corner_size=corner_size,
                locator_engine=locator_engine,
                locator_confidence_threshold=locator_confidence_threshold,
                initial_search_roi=initial_search_roi,
            )
            for i in range(num_workers)
        ]
        self._assembler_thread = AssemblerThread(
            result_queue=self._result_queue,
            assembler=assembler,
            done_event=self.done_event,
            stop_event=self._stop_event,
            stats=self.stats,
            on_frame_callback=on_frame_callback,
        )

    def start(self) -> None:
        self._capture_thread.start()
        for w in self._decode_workers:
            w.start()
        self._assembler_thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Wait until done or timeout. Returns True if completed."""
        return self.done_event.wait(timeout=timeout)

    def join(self, timeout: float = 5.0) -> None:
        """Stop pipeline and join all threads."""
        self.stop()
        self._capture_thread.join(timeout=timeout)
        for w in self._decode_workers:
            w.join(timeout=timeout)
        self._assembler_thread.join(timeout=timeout)

    def check_errors(self) -> None:
        """Raise first worker error if any."""
        for t in [self._capture_thread, self._assembler_thread] + self._decode_workers:
            if getattr(t, "error", None) is not None:
                raise RuntimeError(
                    "pipeline thread {0} failed: {1}".format(t.name, t.error)
                ) from t.error
