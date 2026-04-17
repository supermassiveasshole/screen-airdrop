"""Replay pipeline for offline frame decoding.

This pipeline is designed for replay mode where frames are read from disk
rather than captured from screen. It's much simpler than ScreenLiveRuntime:
- No screen capture
- No preprocessing
- No ROI detection
- Just direct frame decoding in a single thread
"""

import multiprocessing as mp
import threading
import time
from typing import Any, Dict, Optional

import numpy as np

from screen_airdrop.common.transport.protocol_basic import FRAME_DATA
from screen_airdrop.receiver.information import ChunkAssembler
from screen_airdrop.receiver.locator.diagnostics import GeometryDiagnosticsCollector
from screen_airdrop.receiver.locator.factory import build_protocol_geometry_locator
from screen_airdrop.receiver.locator.state_machine import GeometryState, GeometryTracker
from screen_airdrop.receiver.pipeline.base import BasePipeline
from screen_airdrop.receiver.runtime.stats import ScreenLiveRuntimeStats
from screen_airdrop.receiver.transport.decoder_factory import create_protocol_decoder
from screen_airdrop.receiver.transport.layered.observability import (
    make_protocol_report_adapter,
)


def _decode_frame_stateless_process(decoder_kwargs: dict[str, Any], frame):
    decoder = create_protocol_decoder(**decoder_kwargs)
    return decoder.decode_frame(
        frame=frame,
        detect_mode="full",
        forced_roi=None,
    )


def _replay_decode_worker_main(
    task_queue,
    result_queue,
    decoder_kwargs: dict[str, Any],
) -> None:
    decoder = create_protocol_decoder(**decoder_kwargs)
    while True:
        item = task_queue.get()
        if item is None:
            break
        sequence, frame = item
        try:
            decoded = decoder.decode_frame(
                frame=frame,
                detect_mode="full",
                forced_roi=None,
            )
            result_queue.put((int(sequence), True, decoded))
        except Exception as exc:  # pragma: no cover - exercised via parent process handling
            result_queue.put((int(sequence), False, exc))


class ReplayPipeline(BasePipeline):
    """Simple pipeline for replaying captured frames.

    This pipeline reads frames from a FrameReplaySource and decodes them
    directly in a single thread. No screen capture, no preprocessing, no ROI
    detection - just pure decoding for testing and benchmarking.
    """

    def __init__(
        self,
        frame_source,  # FrameReplaySource instance
        assembler: ChunkAssembler,
        protocol: str = "basic",
        decode_workers: int = 1,
        grid_w: int = 160,
        grid_h: int = 96,
        guard_band: int = 2,
        corner_size: int = 9,
        locator_engine: str = "auto",
        locator_confidence_threshold: float = 0.55,
        replay_geometry_mode: str = "stateful",
    ):
        super().__init__(protocol=protocol)

        self.frame_source = frame_source
        self.assembler = assembler
        self.stats = ScreenLiveRuntimeStats(protocol=protocol, prep_mode="none")
        self.stats.protocol_report_adapter = make_protocol_report_adapter(protocol)
        self._replay_geometry_mode = replay_geometry_mode
        self._decode_workers = max(1, int(decode_workers))
        self._parallel_decode_enabled = self._decode_workers > 1 and replay_geometry_mode == "stateless"
        self._decoder_kwargs = {
            "protocol": protocol,
            "grid_w": grid_w,
            "grid_h": grid_h,
            "guard_band": guard_band,
            "corner_size": corner_size,
            "locator_engine": locator_engine,
            "locator_confidence_threshold": locator_confidence_threshold,
        }

        # Create report collector
        self.report_collector = self._create_report_collector(
            stats=self.stats,
            assembler=assembler,
        )

        # Threading primitives
        self._stop_event = threading.Event()
        self.done_event = threading.Event()
        self._error: Optional[Exception] = None

        # Create protocol decoder using factory
        self._decoder = create_protocol_decoder(**self._decoder_kwargs)
        self._geometry_tracker: Optional[GeometryTracker] = None
        self._geometry_diagnostics: Optional[GeometryDiagnosticsCollector] = None
        self._stateful_geometry_enabled = (
            replay_geometry_mode == "stateful"
            and protocol == "layered"
            and hasattr(self._decoder, "decode_frame_with_geometry")
            and callable(getattr(self._decoder, "locate_geometry", None))
            and callable(getattr(self._decoder, "geometry_from_locate_result", None))
        )
        if self._stateful_geometry_enabled:
            self._geometry_tracker = self._create_geometry_tracker(
                grid_w=grid_w,
                grid_h=grid_h,
                guard_band=guard_band,
                corner_size=corner_size,
            )
            self._geometry_diagnostics = GeometryDiagnosticsCollector()

        # Main processing thread
        self._main_thread: Optional[threading.Thread] = None

    def _create_geometry_tracker(
        self,
        *,
        grid_w: int,
        grid_h: int,
        guard_band: int,
        corner_size: int,
    ) -> GeometryTracker:
        del grid_w, grid_h, guard_band, corner_size
        locator = build_protocol_geometry_locator(self._decoder)
        return GeometryTracker(
            locator=locator,
            stream_id="replay:0",
            search_policy="roi_then_expand",
            locate_to_geometry=self._runtime_geometry_from_locate_result,
            locator_confidence_threshold=0.55,
        )

    def _runtime_geometry_from_locate_result(self, locate_result: object, generation: int):
        raw_geometry = self._decoder.geometry_from_locate_result(locate_result, generation)
        if raw_geometry is None:
            return None
        return GeometryState(
            stream_id="replay:0",
            geometry_generation=generation,
            quad_src=np.array(raw_geometry.quad_src, copy=True),
            homography=np.array(raw_geometry.homography, copy=True),
            homography_inv=np.array(raw_geometry.homography_inv, copy=True),
            source_capture_index=0,
            last_success_frame_id=0,
            last_success_chunk_id=0,
            quality_score=float(raw_geometry.det_confidence),
            lock_mode="locked",
            grid_bbox_std=(
                int(raw_geometry.grid_bbox_std[0]),
                int(raw_geometry.grid_bbox_std[1]),
                int(raw_geometry.grid_bbox_std[2]),
                int(raw_geometry.grid_bbox_std[3]),
            ),
            warped_shape=(
                int(raw_geometry.warped_shape[0]),
                int(raw_geometry.warped_shape[1]),
            ),
            locator_engine=str(raw_geometry.locator_engine),
            det_confidence=float(raw_geometry.det_confidence),
            homography_rmse=float(raw_geometry.homography_rmse),
            protocol_geometry=raw_geometry,
        )

    def _probe_runtime_geometry(self, frame, geometry: GeometryState):
        raw_geometry = geometry.protocol_geometry
        if raw_geometry is None:
            raise ValueError("runtime geometry missing protocol geometry")
        return self._decoder.probe_geometry(frame, raw_geometry)

    def start(self) -> None:
        """Start the pipeline."""
        self._main_thread = threading.Thread(target=self._run, daemon=True)
        self._main_thread.start()

    def _run(self) -> None:
        """Main processing loop - decode frames sequentially."""
        try:
            if self._parallel_decode_enabled:
                self._run_parallel_stateless()
            else:
                self._run_sequential()

        except Exception as exc:
            self._error = exc

        finally:
            self.done_event.set()

    def stop(self) -> None:
        """Stop the pipeline."""
        self._stop_event.set()

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Wait for pipeline to complete."""
        return self.done_event.wait(timeout=timeout)

    def join(self, timeout: float = 10.0) -> None:
        """Stop and clean up pipeline resources."""
        self.stop()

        # Wait for main thread
        if self._main_thread:
            self._main_thread.join(timeout=timeout)

    def check_errors(self) -> None:
        """Check and raise pipeline errors."""
        if self._error:
            raise self._error

    def snapshot(self) -> Dict[str, Any]:
        """Get pipeline statistics snapshot."""
        snap = self.stats.snapshot()
        snap["runtime_mode"] = "replay"
        snap["producer_mode"] = "frames_dir"
        if self._geometry_tracker is not None:
            snap.update(self._geometry_tracker.snapshot().as_dict())
            snap["replay_geometry_mode"] = self._replay_geometry_mode
        if self._geometry_diagnostics is not None:
            snap.update(self._geometry_diagnostics.as_dict())
        snap["replay_decode_workers"] = self._decode_workers
        snap["replay_parallel_decode_enabled"] = self._parallel_decode_enabled
        return snap

    def _run_sequential(self) -> None:
        for frame in self.frame_source.iter_frames():
            if self._stop_event.is_set():
                break
            with self.stats._lock:
                self.stats.captured += 1
                frame_index = int(self.stats.captured)
            try:
                if self._geometry_tracker is not None:
                    decoded = self._decode_frame_stateful(frame=frame, frame_index=frame_index)
                else:
                    decoded = self._decoder.decode_frame(
                        frame=frame,
                        detect_mode="full",
                        forced_roi=None,
                    )
                if self._handle_decode_success(decoded):
                    break
            except Exception as exc:
                self._handle_decode_failure(exc)

    def _run_parallel_stateless(self) -> None:
        max_pending = max(self._decode_workers * 4, self._decode_workers)
        next_sequence = 0
        next_commit = 0
        pending_results: Dict[int, tuple[bool, Any]] = {}
        pending_count = 0
        ctx = mp.get_context("spawn")
        task_queue = ctx.Queue(maxsize=max_pending)
        result_queue = ctx.Queue()
        workers = [
            ctx.Process(
                target=_replay_decode_worker_main,
                args=(task_queue, result_queue, self._decoder_kwargs),
                name=f"ReplayDecode-{worker_id}",
            )
            for worker_id in range(self._decode_workers)
        ]
        for worker in workers:
            worker.start()
        try:
            for frame in self.frame_source.iter_frames():
                if self._stop_event.is_set():
                    break
                with self.stats._lock:
                    self.stats.captured += 1
                task_queue.put((next_sequence, frame))
                next_sequence += 1
                pending_count += 1
                while pending_count >= max_pending or self._stop_event.is_set():
                    sequence, ok, payload = result_queue.get()
                    pending_results[int(sequence)] = (bool(ok), payload)
                    pending_count -= 1
                    while next_commit in pending_results:
                        ok, payload = pending_results.pop(next_commit)
                        if self._consume_pending_result(ok=ok, payload=payload):
                            self._stop_event.set()
                            return
                        next_commit += 1
            while pending_count > 0:
                sequence, ok, payload = result_queue.get()
                pending_results[int(sequence)] = (bool(ok), payload)
                pending_count -= 1
                while next_commit in pending_results:
                    ok, payload = pending_results.pop(next_commit)
                    if self._consume_pending_result(ok=ok, payload=payload):
                        self._stop_event.set()
                        return
                    next_commit += 1
        finally:
            for _ in workers:
                task_queue.put(None)
            for worker in workers:
                worker.join(timeout=5.0)
                if worker.is_alive():
                    worker.terminate()
                    worker.join(timeout=1.0)

    def _consume_pending_result(self, *, ok: bool, payload: Any) -> bool:
        if not ok:
            self._handle_decode_failure(payload)
            return False
        return self._handle_decode_success(payload)

    def _handle_decode_success(self, decoded) -> bool:
        header = decoded.frame_header
        payload = decoded.payload
        meta = decoded.meta
        with self.stats._lock:
            self.stats.decode_ok += 1
            decoded_ts = time.time()
            if self.stats.first_valid_frame_ts is None:
                self.stats.first_valid_frame_ts = decoded_ts
            if int(header.frame_type) == int(FRAME_DATA) and self.stats.first_data_frame_ts is None:
                self.stats.first_data_frame_ts = decoded_ts
            self.stats.protocol_report_adapter.accumulate_success(meta)
        if self.report_collector:
            self.report_collector.on_decode_success(meta)
        if header.frame_type == FRAME_DATA:
            control_kind = decoded.control_kind
            if control_kind is not None:
                with self.stats._lock:
                    if self.stats.first_new_chunk_ts is None:
                        self.stats.startup_control_frames_decoded += 1
                try:
                    self.assembler.add_control(control_kind, payload)
                except Exception:
                    pass
            elif decoded.invalid_data_payload:
                self.assembler.note_invalid_coded_payload(decoded.invalid_data_reason)
            elif decoded.transmission_unit is not None or header.chunk_id > 0:
                is_new_chunk = (
                    self.assembler.add_unit(decoded.transmission_unit)
                    if decoded.transmission_unit is not None
                    else self.assembler.add(header.chunk_id, payload)
                )
                with self.stats._lock:
                    if is_new_chunk:
                        self.stats.decoded_new_chunks += 1
                        self.stats.assembled += 1
                        self.stats.assembled_bytes += len(payload)
                        if self.stats.first_new_chunk_ts is None:
                            self.stats.first_new_chunk_ts = decoded_ts
                    else:
                        self.stats.decoded_duplicate_chunks += 1
        else:
            with self.stats._lock:
                if self.stats.first_new_chunk_ts is None:
                    self.stats.startup_sync_frames_decoded += 1
        if self.assembler.complete():
            self.done_event.set()
            return True
        return False

    def _handle_decode_failure(self, exc: Exception) -> None:
        with self.stats._lock:
            self.stats.decode_fail += 1
            self.stats.decode_exceptions += 1
            self.stats.last_decode_error = str(exc)
            failure_class = str(getattr(exc, "failure_class", "") or "")
            self.stats.last_failure_class = failure_class
            if failure_class == "header":
                self.stats.failure_count_header += 1
            elif failure_class == "payload":
                self.stats.failure_count_payload += 1
            elif failure_class == "locator":
                self.stats.failure_count_locator += 1
            elif failure_class:
                self.stats.failure_count_unknown += 1
            self.stats.protocol_report_adapter.accumulate_failure(
                str(exc),
                failure_class=failure_class,
                trace=getattr(exc, "context", None),
            )
        if self.report_collector:
            self.report_collector.on_decode_failure(
                error=str(exc),
                failure_class=failure_class,
                context={},
            )

    def _decode_frame_stateful(self, *, frame, frame_index: int):
        assert self._geometry_tracker is not None
        decision = self._geometry_tracker.submit_frame(frame, frame_index)
        if decision.reuse_first and decision.accepted_geometry is not None:
            with self.stats._lock:
                self.stats.lock_decode_mode_geometry_reuse += 1
            try:
                decoded = self._decoder.decode_frame_with_geometry(
                    frame=frame,
                    geometry=decision.accepted_geometry.protocol_geometry,
                )
            except Exception:
                should_reacquire = self._geometry_tracker.record_failure(
                    decode_mode="geometry_reuse"
                )
                with self.stats._lock:
                    self.stats.geometry_reuse_fail_count += 1
                    if should_reacquire:
                        self.stats.lock_locked_to_acquire += 1
                self._capture_failure_diagnostics(frame=frame, frame_index=frame_index)
                raise
            self._geometry_tracker.record_success(
                bbox=getattr(decoded.meta, "det_bbox", None),
                decode_mode="geometry_reuse",
            )
            with self.stats._lock:
                self.stats.geometry_reuse_success_count += 1
            return decoded

        with self.stats._lock:
            self.stats.lock_decode_mode_reacquire_locator += 1

        if decision.reacquire_attempted:
            with self.stats._lock:
                self.stats.reacquire_attempt_count += 1

        if decision.candidate_geometry is None:
            self._geometry_tracker.record_failure(decode_mode="reacquire_locator")
            with self.stats._lock:
                self.stats.reacquire_fail_count += 1
            self._capture_failure_diagnostics(frame=frame, frame_index=frame_index)
            raise RuntimeError("geometry reacquire failed")

        try:
            decoded = self._decoder.decode_frame_with_geometry(
                frame=frame,
                geometry=decision.candidate_geometry.protocol_geometry,
            )
        except Exception:
            self._geometry_tracker.record_failure(decode_mode="reacquire_locator")
            with self.stats._lock:
                self.stats.reacquire_fail_count += 1
            self._capture_failure_diagnostics(frame=frame, frame_index=frame_index)
            raise
        self._geometry_tracker.propose_update(
            proposed_geometry=decision.candidate_geometry,
            decode_quality=float(getattr(decoded.meta, "det_confidence", 0.0) or 0.0),
            used_geometry_generation=self._geometry_tracker.current_generation,
            meta=decoded.meta,
        )
        self._geometry_tracker.record_success(
            geometry=decision.candidate_geometry,
            bbox=getattr(decoded.meta, "det_bbox", None),
            decode_mode="reacquire_locator",
        )
        with self.stats._lock:
            self.stats.reacquire_success_count += 1
        return decoded

    def _capture_failure_diagnostics(self, *, frame, frame_index: int) -> None:
        if self._geometry_diagnostics is None:
            return
        locator = build_protocol_geometry_locator(self._decoder)
        locate_result = locator.locate(frame)
        self._geometry_diagnostics.inspect_failure(
            frame=frame,
            frame_index=frame_index,
            state=(
                "unknown"
                if self._geometry_tracker is None
                else self._geometry_tracker.lock_mode
            ),
            trusted_geometry_age_frames=(
                0
                if self._geometry_tracker is None
                else self._geometry_tracker.get_locked_geometry_age()
            ),
            locate_result=locate_result if hasattr(locate_result, "quad_src") else None,
            locate_to_geometry=self._runtime_geometry_from_locate_result,
            probe_geometry=self._probe_runtime_geometry,
        )
