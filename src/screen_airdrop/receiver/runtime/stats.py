"""Runtime statistics and metrics collection."""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol, cast

from screen_airdrop.receiver.protocol_observability import make_protocol_report_adapter


class ProtocolReportAdapterProtocol(Protocol):
    """Protocol for protocol-specific report adapters."""

    def finalize_summary(self) -> Mapping[str, object]: ...
    def accumulate_success(self, meta: object) -> None: ...
    def accumulate_failure(
        self, error: str, *, failure_class: str, trace: Optional[Dict[str, object]]
    ) -> None: ...


@dataclass
class ScreenLiveRuntimeStats:
    """Runtime statistics for screen live capture pipeline."""

    protocol: str
    prep_mode: str = "async"
    prep_processes: int = 0
    start_ts: float = field(default_factory=time.time)

    # Frame counts
    captured: int = 0
    duplicate_frames: int = 0
    decode_ok: int = 0
    decode_fail: int = 0
    decode_exceptions: int = 0
    dropped_result_queue_full: int = 0
    assembled: int = 0
    assembled_bytes: int = 0
    dropped_queue_full: int = 0

    # Timing metrics (ms)
    capture_grab_time_ms: float = 0.0
    capture_grab_ops: int = 0
    capture_copy_time_ms: float = 0.0
    capture_copy_ops: int = 0
    capture_dedup_time_ms: float = 0.0
    capture_dedup_ops: int = 0
    fingerprint_time_ms: float = 0.0
    fingerprint_ops: int = 0
    materialize_time_ms: float = 0.0
    materialize_ops: int = 0
    dump_time_ms: float = 0.0
    dump_ops: int = 0
    ipc_recv_time_ms: float = 0.0
    ipc_recv_ops: int = 0
    slot_wait_ms: float = 0.0
    slot_wait_ops: int = 0
    dedup_decision_ms: float = 0.0
    dedup_decision_ops: int = 0

    # Pipeline metrics
    raw_grab_frames: int = 0
    prep_processed_frames: int = 0
    accepted_for_decode_frames: int = 0
    decode_queue_depth: int = 0
    decode_queue_depth_peak: int = 0
    prep_backlog_frames: int = 0
    prep_backlog_peak: int = 0
    capture_overwrite_count: int = 0
    capture_overwrite_before_prep: int = 0
    dropped_slot_unavailable: int = 0
    dropped_dump_backpressure: int = 0
    slot_in_use_peak: int = 0
    slot_generation_mismatch: int = 0

    # Startup timing
    first_valid_frame_ts: Optional[float] = None
    first_data_frame_ts: Optional[float] = None
    first_new_chunk_ts: Optional[float] = None
    startup_sync_frames_decoded: int = 0
    startup_control_frames_decoded: int = 0
    decoded_new_chunks: int = 0
    decoded_duplicate_chunks: int = 0

    # Geometry lock metrics
    lock_acquire_to_locked: int = 0
    lock_locked_to_acquire: int = 0
    locked_decode_fail_streak_max: int = 0
    lock_decode_mode_geometry_reuse: int = 0
    lock_decode_mode_reacquire_locator: int = 0
    geometry_reuse_success_count: int = 0
    geometry_reuse_fail_count: int = 0
    reacquire_attempt_count: int = 0
    reacquire_success_count: int = 0
    reacquire_fail_count: int = 0
    locked_geometry_age_max: int = 0
    homography_rmse_reused_last: float = 0.0
    homography_rmse_reacquired_last: float = 0.0

    # Error tracking
    last_decode_error: str = ""
    last_failure_class: str = ""
    failure_count_header: int = 0
    failure_count_payload: int = 0
    failure_count_locator: int = 0
    failure_count_unknown: int = 0

    # Protocol-specific adapter
    protocol_report_adapter: ProtocolReportAdapterProtocol = field(
        default_factory=lambda: cast(
            ProtocolReportAdapterProtocol, make_protocol_report_adapter("")
        )
    )

    # Thread safety
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> Dict[str, Any]:
        """Create a snapshot of current statistics.

        Returns:
            Dictionary with all metrics and computed rates
        """
        with self._lock:
            snap: Dict[str, Any] = {
                "captured": self.captured,
                "duplicate_frames": self.duplicate_frames,
                "decode_ok": self.decode_ok,
                "decode_fail": self.decode_fail,
                "decode_exceptions": self.decode_exceptions,
                "dropped_result_queue_full": self.dropped_result_queue_full,
                "assembled": self.assembled,
                "assembled_bytes": self.assembled_bytes,
                "dropped_queue_full": self.dropped_queue_full,
                "capture_grab_time_ms": self.capture_grab_time_ms,
                "capture_grab_ops": self.capture_grab_ops,
                "capture_copy_time_ms": self.capture_copy_time_ms,
                "capture_copy_ops": self.capture_copy_ops,
                "capture_dedup_time_ms": self.capture_dedup_time_ms,
                "capture_dedup_ops": self.capture_dedup_ops,
                "fingerprint_time_ms": self.fingerprint_time_ms,
                "fingerprint_ops": self.fingerprint_ops,
                "materialize_time_ms": self.materialize_time_ms,
                "materialize_ops": self.materialize_ops,
                "dump_time_ms": self.dump_time_ms,
                "dump_ops": self.dump_ops,
                "ipc_recv_time_ms": self.ipc_recv_time_ms,
                "ipc_recv_ops": self.ipc_recv_ops,
                "slot_wait_ms": self.slot_wait_ms,
                "slot_wait_ops": self.slot_wait_ops,
                "dedup_decision_ms": self.dedup_decision_ms,
                "dedup_decision_ops": self.dedup_decision_ops,
                "raw_grab_frames": self.raw_grab_frames,
                "prep_processed_frames": self.prep_processed_frames,
                "accepted_for_decode_frames": self.accepted_for_decode_frames,
                "decode_queue_depth": self.decode_queue_depth,
                "prep_backlog_frames": self.prep_backlog_frames,
                "capture_overwrite_count": self.capture_overwrite_count,
                "capture_overwrite_before_prep": self.capture_overwrite_before_prep,
                "dropped_raw_queue_full": 0,
                "dropped_prep_queue_full": 0,
                "dropped_dump_queue_full": self.dropped_dump_backpressure,
                "shared_memory_bytes_peak": 0,
                "pipeline_dropped_slot_unavailable": self.dropped_slot_unavailable,
                "pipeline_dropped_dump_backpressure": self.dropped_dump_backpressure,
                "pipeline_slot_in_use_peak": self.slot_in_use_peak,
                "pipeline_slot_generation_mismatch": self.slot_generation_mismatch,
                "pipeline_decode_attach_ms": self.ipc_recv_time_ms,
                "pipeline_prep_mode": self.prep_mode,
                "pipeline_prep_processes": self.prep_processes,
                "raw_grab_fps": 0.0,
                "prep_fps": 0.0,
                "accepted_for_decode_fps": 0.0,
                "time_to_first_valid_frame_s": (
                    0.0
                    if self.first_valid_frame_ts is None
                    else max(0.0, self.first_valid_frame_ts - self.start_ts)
                ),
                "time_to_first_data_frame_s": (
                    0.0
                    if self.first_data_frame_ts is None
                    else max(0.0, self.first_data_frame_ts - self.start_ts)
                ),
                "time_to_first_new_chunk_s": (
                    0.0
                    if self.first_new_chunk_ts is None
                    else max(0.0, self.first_new_chunk_ts - self.start_ts)
                ),
                "startup_sync_frames_decoded": self.startup_sync_frames_decoded,
                "startup_control_frames_decoded": self.startup_control_frames_decoded,
                "decoded_new_chunks": self.decoded_new_chunks,
                "decoded_duplicate_chunks": self.decoded_duplicate_chunks,
                "lock_acquire_to_locked": self.lock_acquire_to_locked,
                "lock_locked_to_acquire": self.lock_locked_to_acquire,
                "locked_decode_fail_streak_max": self.locked_decode_fail_streak_max,
                "lock_decode_mode_counts": {
                    "geometry_reuse": self.lock_decode_mode_geometry_reuse,
                    "reacquire_locator": self.lock_decode_mode_reacquire_locator,
                },
                "geometry_reuse_success_count": self.geometry_reuse_success_count,
                "geometry_reuse_fail_count": self.geometry_reuse_fail_count,
                "reacquire_attempt_count": self.reacquire_attempt_count,
                "reacquire_success_count": self.reacquire_success_count,
                "reacquire_fail_count": self.reacquire_fail_count,
                "locked_geometry_age_max": self.locked_geometry_age_max,
                "homography_rmse_reused_last": self.homography_rmse_reused_last,
                "homography_rmse_reacquired_last": self.homography_rmse_reacquired_last,
                "last_decode_error": self.last_decode_error,
                "last_failure_class": self.last_failure_class,
                "failure_count_header": self.failure_count_header,
                "failure_count_payload": self.failure_count_payload,
                "failure_count_locator": self.failure_count_locator,
                "failure_count_unknown": self.failure_count_unknown,
            }

            # Add protocol-specific metrics
            snap.update(dict(self.protocol_report_adapter.finalize_summary()))

            # Compute FPS rates
            elapsed = max(0.001, time.time() - self.start_ts)
            snap["raw_grab_fps"] = self.raw_grab_frames / elapsed
            snap["prep_fps"] = self.prep_processed_frames / elapsed
            snap["accepted_for_decode_fps"] = self.accepted_for_decode_frames / elapsed

            return snap
