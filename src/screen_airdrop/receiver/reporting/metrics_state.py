"""Metrics state container for receiver reporting.

This module provides a centralized state container for all metrics collected
during receiver operation, replacing scattered local variables in cli.py.
"""

from typing import Dict, List, Optional, Tuple


class MetricsState:
    """Container for all receiver metrics and state.

    This class replaces the many local variables in main() that track
    decode metrics, failure counts, timing information, etc.
    """

    def __init__(self, protocol: str):
        """Initialize metrics state.

        Args:
            protocol: Protocol name (basic, compact, gray4, layered)
        """
        self.protocol = protocol

        # Protocol and decode metrics
        self.protocol_path_used = protocol
        self.decode_attempt_total = 0
        self.fallback_hits = 0
        self.decode_time_sum = 0.0
        self.decode_time_count = 0

        # Locator metrics
        self.locator_new_fail_reason = ""
        self.locator_new_elapsed_ms = 0.0
        self.locator_legacy_used = False
        self.locator_legacy_elapsed_ms = 0.0

        # Bounding box jitter tracking
        self.bbox_jitter_sum = 0.0
        self.bbox_jitter_count = 0
        self.prev_bbox: Optional[Tuple[int, int, int, int]] = None
        self.last_det_bbox: Optional[Tuple[int, int, int, int]] = None
        self.last_det_confidence = 0.0

        # Decode error tracking
        self.last_decode_error: Optional[str] = None
        self.last_gray4_failure_error: Optional[str] = None
        self.last_gray4_failure_class = ""
        self.gray4_failure_counts = {
            "header": 0,
            "payload": 0,
            "locator": 0,
            "unknown": 0,
        }

        # Layered protocol specific
        self.layered_failure_counts = {
            "control_prefix": 0,
            "format": 0,
            "bootstrap_rs": 0,
            "bootstrap_crc": 0,
            "body_rs": 0,
            "body_crc": 0,
        }
        self.layered_failure_trace: Optional[Dict[str, object]] = None
        self.layered_format_attempt_count = 0
        self.layered_format_fallback_attempts = 0
        self.layered_format_fallback_successes = 0
        self.layered_format_primary_threshold_sum = 0.0
        self.layered_format_primary_threshold_count = 0
        self.layered_format_fallback_threshold_sum = 0.0
        self.layered_format_fallback_threshold_count = 0
        self.layered_format_vote_margin_sum = 0.0
        self.layered_format_vote_margin_count = 0
        self.layered_format_vote_margin_min = float("inf")
        self.layered_format_mask_fail_counts: Dict[str, int] = {}
        self.layered_format_bit_fail_counts: List[int] = [0] * 80
        self.layered_format_line_fail_horizontal = 0
        self.layered_format_line_fail_vertical = 0
        self.layered_format_fail_examples: List[Dict[str, object]] = []
        self.layered_bootstrap_threshold_fallback_attempts = 0
        self.layered_bootstrap_threshold_fallback_successes = 0

        # Geometry locking (layered protocol)
        self.layered_locked_geometry = None
        self.layered_locked_fail_streak = 0
        self.layered_locked_geometry_age = 0
        self.layered_locked_fail_reacquire_threshold = 5
        self.lock_decode_mode_geometry_reuse = 0
        self.lock_decode_mode_reacquire_locator = 0
        self.geometry_reuse_success_count = 0
        self.geometry_reuse_fail_count = 0
        self.reacquire_attempt_count = 0
        self.reacquire_success_count = 0
        self.reacquire_fail_count = 0
        self.locked_geometry_age_max = 0
        self.homography_rmse_reused_last = 0.0
        self.homography_rmse_reacquired_last = 0.0

        # Tracking ROI state
        self.v3_track_roi: Optional[Tuple[int, int, int, int]] = None
        self.v3_fail_streak = 0
        self.v3_mode = "track"

        # Metadata from last successful decode
        self.last_v3_meta = None
        self.last_v31_meta = None

        # Startup and chunk tracking
        self.first_valid_frame_ts: Optional[float] = None
        self.first_data_frame_ts: Optional[float] = None
        self.first_new_chunk_ts: Optional[float] = None
        self.startup_sync_frames_decoded = 0
        self.startup_control_frames_decoded = 0
        self.decoded_new_chunks = 0
        self.decoded_duplicate_chunks = 0

        # Auto-fail tracking for manual ROI fallback
        self.auto_fail_count = 0
        self.manual_attempts = 0

    def record_bbox_jitter(self, bbox: Tuple[int, int, int, int]) -> None:
        """Record bounding box jitter for stability metrics.

        Args:
            bbox: Current bounding box (x, y, w, h)
        """
        if self.prev_bbox is not None:
            px, py, pw, ph = self.prev_bbox
            bx, by, bw, bh = bbox
            dx = abs(bx - px) + abs(by - py) + abs(bw - pw) + abs(bh - ph)
            self.bbox_jitter_sum += float(dx)
            self.bbox_jitter_count += 1
        self.prev_bbox = bbox

    def update_from_meta(self, meta) -> None:
        """Update state from decode metadata.

        Args:
            meta: Decode metadata object (v31 format)
        """
        self.last_v31_meta = meta
        self.last_det_bbox = meta.det_bbox
        self.last_det_confidence = float(meta.det_confidence)
        self.locator_new_fail_reason = meta.new_fail_reason
        self.locator_new_elapsed_ms = float(meta.new_elapsed_ms)
        self.locator_legacy_used = bool(meta.legacy_used)
        self.locator_legacy_elapsed_ms = float(meta.legacy_elapsed_ms)
        self.v3_fail_streak = 0

        # Record bbox jitter
        if meta.det_bbox:
            self.record_bbox_jitter(meta.det_bbox)

    def record_decode_time(self, elapsed_seconds: float) -> None:
        """Record decode timing.

        Args:
            elapsed_seconds: Decode time in seconds
        """
        self.decode_time_sum += elapsed_seconds
        self.decode_time_count += 1

    def record_decode_failure(self, error: str, failure_class: str = "") -> None:
        """Record decode failure.

        Args:
            error: Error message
            failure_class: Failure classification (header, payload, locator, etc.)
        """
        self.last_decode_error = error

        if self.protocol in ("gray4", "layered"):
            self.last_gray4_failure_error = error
            self.last_gray4_failure_class = failure_class

            if failure_class in self.gray4_failure_counts:
                self.gray4_failure_counts[failure_class] += 1
            elif failure_class:
                self.gray4_failure_counts["unknown"] += 1

    def clear_decode_error(self) -> None:
        """Clear decode error state after successful decode."""
        self.last_decode_error = None
        if self.protocol in ("gray4", "layered"):
            self.last_gray4_failure_error = None
            self.last_gray4_failure_class = ""
