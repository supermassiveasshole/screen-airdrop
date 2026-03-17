"""Report builder for receiver metrics.

This module provides report building functionality, replacing the nested
_attach_* functions in cli.py main().
"""

from typing import Dict, Mapping, Optional

from screen_airdrop.common.ecc_rs import LAYERED_BOOTSTRAP_RS
from screen_airdrop.common.protocol_layered import layered_bootstrap_payload_size_bytes


def _as_float(value: object, default: float = 0.0) -> float:
    """Convert value to float safely."""
    if value is None:
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)  # type: ignore[arg-type]
    except Exception:
        return default


def _as_int(value: object, default: int = 0) -> int:
    """Convert value to int safely."""
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(value)  # type: ignore[arg-type]
    except Exception:
        return default


class ReportBuilder:
    """Builds final JSON reports from metrics state.

    This class replaces the nested _attach_* functions in cli.py,
    providing a cleaner interface for report generation.
    """

    def __init__(self, metrics_state, stats, debug_manager=None):
        """Initialize report builder.

        Args:
            metrics_state: MetricsState instance
            stats: TransferStats instance
            debug_manager: Optional DebugSnapshotManager instance
        """
        self.m = metrics_state
        self.stats = stats
        self.debug_manager = debug_manager

    def attach_v3_metrics(self, report: Dict[str, object]) -> None:
        """Attach V3 decode metrics to report.

        Args:
            report: Report dictionary to update
        """
        if self.m.protocol_path_used:
            report["protocol_path_used"] = self.m.protocol_path_used

        report["decode_attempts_per_frame"] = float(self.m.decode_attempt_total) / float(
            max(1, self.stats.total_frames)
        )
        report["fallback_ratio"] = float(self.m.fallback_hits) / float(
            max(1, self.stats.valid_frames)
        )
        report["homography_stability"] = (
            self.m.bbox_jitter_sum / float(max(1, self.m.bbox_jitter_count))
            if self.m.bbox_jitter_count > 0
            else 0.0
        )
        report["avg_decode_ms"] = (
            self.m.decode_time_sum / float(max(1, self.m.decode_time_count))
        ) * 1000.0

        if self.debug_manager:
            report["avg_debug_dump_ms"] = (
                self.debug_manager.debug_time_sum
                / float(max(1, self.debug_manager.debug_time_count))
            ) * 1000.0
        else:
            report["avg_debug_dump_ms"] = 0.0

        report["new_fail_reason"] = self.m.locator_new_fail_reason
        report["new_elapsed_ms"] = float(self.m.locator_new_elapsed_ms)
        report["legacy_used"] = 1.0 if self.m.locator_legacy_used else 0.0
        report["legacy_elapsed_ms"] = float(self.m.locator_legacy_elapsed_ms)

    def attach_gray4_state(
        self,
        report: Dict[str, object],
        *,
        failure_error: Optional[str] = None,
        failure_class: str = "",
        success_meta: Optional[object] = None,
        failure_counts: Optional[Mapping[str, object]] = None,
    ) -> None:
        """Attach gray4/layered protocol state to report.

        Args:
            report: Report dictionary to update
            failure_error: Last failure error message
            failure_class: Last failure classification
            success_meta: Last successful decode metadata
            failure_counts: Failure count mapping
        """
        if self.m.protocol not in ("gray4", "layered"):
            return

        report["gray4_last_failure_error"] = "" if failure_error is None else str(failure_error)
        report["gray4_last_failure_class"] = str(failure_class or "")

        if failure_counts is not None:
            report["gray4_failure_counts"] = {
                "header": int(failure_counts.get("header", 0) or 0),  # type: ignore[arg-type]
                "payload": int(failure_counts.get("payload", 0) or 0),  # type: ignore[arg-type]
                "locator": int(failure_counts.get("locator", 0) or 0),  # type: ignore[arg-type]
                "unknown": int(failure_counts.get("unknown", 0) or 0),  # type: ignore[arg-type]
            }

        if success_meta is None:
            return

        report["gray4_last_mask_id"] = float(getattr(success_meta, "mask_id", -1))
        report["gray4_avg_symbol_confidence"] = float(
            getattr(success_meta, "avg_symbol_confidence", 0.0)
        )
        report["gray4_total_decode_ms"] = float(getattr(success_meta, "total_decode_ms", 0.0))
        report["gray4_payload_low_conf_symbols"] = float(
            getattr(success_meta, "payload_low_conf_symbols", 0)
        )
        report["gray4_payload_variant_attempts"] = float(
            getattr(success_meta, "payload_variant_attempts", 0)
        )

        if self.m.protocol == "layered":
            self._attach_layered_metrics(report)

    def _attach_layered_metrics(self, report: Dict[str, object]) -> None:
        """Attach layered protocol specific metrics.

        Args:
            report: Report dictionary to update
        """
        report["layered_control_path_version"] = 4.0
        report["layered_core_header_raw_bytes"] = float(layered_bootstrap_payload_size_bytes())
        report["layered_core_header_coded_bytes"] = float(
            layered_bootstrap_payload_size_bytes() + int(LAYERED_BOOTSTRAP_RS.nsym)
        )
        report["layered_core_header_ecc_nsym"] = float(LAYERED_BOOTSTRAP_RS.nsym)
        report["layered_core_header_attempt_count"] = float(self.m.layered_format_attempt_count)
        report["layered_core_header_threshold_avg"] = (
            0.0
            if self.m.layered_format_primary_threshold_count <= 0
            else self.m.layered_format_primary_threshold_sum
            / float(self.m.layered_format_primary_threshold_count)
        )
        report["layered_core_header_vote_margin_min"] = float(
            self.m.layered_format_vote_margin_min
        )
        report["layered_core_header_vote_margin_avg"] = (
            0.0
            if self.m.layered_format_vote_margin_count <= 0
            else self.m.layered_format_vote_margin_sum
            / float(self.m.layered_format_vote_margin_count)
        )
        report["layered_core_header_erasure_symbol_count_avg"] = 0.0
        report["layered_core_header_erasure_symbol_count_max"] = 0.0
        report["layered_core_header_errata_corrected_avg"] = 0.0
        report["layered_core_header_errata_corrected_max"] = 0.0
        report["layered_core_header_rs_fail_count"] = float(
            self.m.layered_failure_counts["bootstrap_rs"]
        )
        report["layered_core_header_crc_fail_count"] = float(
            self.m.layered_failure_counts["bootstrap_crc"]
        )
        report["layered_core_header_fail_examples"] = list(self.m.layered_format_fail_examples)
        report["layered_control_prefix_fail_count"] = 0.0
        report["layered_format_fail_count"] = 0.0
        report["layered_bootstrap_attempt_count"] = float(self.m.layered_format_attempt_count)
        report["layered_bootstrap_threshold_avg"] = (
            0.0
            if self.m.layered_format_primary_threshold_count <= 0
            else self.m.layered_format_primary_threshold_sum
            / float(self.m.layered_format_primary_threshold_count)
        )
        report["layered_bootstrap_vote_margin_min"] = float(self.m.layered_format_vote_margin_min)
        report["layered_bootstrap_vote_margin_avg"] = (
            0.0
            if self.m.layered_format_vote_margin_count <= 0
            else self.m.layered_format_vote_margin_sum
            / float(self.m.layered_format_vote_margin_count)
        )
        report["layered_bootstrap_bit_fail_counts"] = list(self.m.layered_format_bit_fail_counts)
        report["layered_bootstrap_fail_examples"] = list(self.m.layered_format_fail_examples)
        report["layered_bootstrap_rs_fail_count"] = float(
            self.m.layered_failure_counts["bootstrap_rs"]
        )
        report["layered_bootstrap_crc_fail_count"] = float(
            self.m.layered_failure_counts["bootstrap_crc"]
        )
        report["layered_body_rs_fail_count"] = float(self.m.layered_failure_counts["body_rs"])
        report["layered_body_crc_fail_count"] = float(self.m.layered_failure_counts["body_crc"])
        report["layered_format_attempt_count"] = float(self.m.layered_format_attempt_count)
        report["layered_format_fallback_attempts"] = float(
            self.m.layered_format_fallback_attempts
        )
        report["layered_format_fallback_successes"] = float(
            self.m.layered_format_fallback_successes
        )
        report["layered_format_primary_threshold_avg"] = (
            0.0
            if self.m.layered_format_primary_threshold_count <= 0
            else self.m.layered_format_primary_threshold_sum
            / float(self.m.layered_format_primary_threshold_count)
        )
        report["layered_format_fallback_threshold_avg"] = (
            0.0
            if self.m.layered_format_fallback_threshold_count <= 0
            else self.m.layered_format_fallback_threshold_sum
            / float(self.m.layered_format_fallback_threshold_count)
        )
        report["layered_format_vote_margin_min"] = float(self.m.layered_format_vote_margin_min)
        report["layered_format_vote_margin_avg"] = (
            0.0
            if self.m.layered_format_vote_margin_count <= 0
            else self.m.layered_format_vote_margin_sum
            / float(self.m.layered_format_vote_margin_count)
        )
        report["layered_format_mask_fail_counts"] = dict(self.m.layered_format_mask_fail_counts)
        report["layered_format_bit_fail_counts"] = list(self.m.layered_format_bit_fail_counts)
        report["layered_format_line_fail_counts"] = {
            "horizontal": int(self.m.layered_format_line_fail_horizontal),
            "vertical": int(self.m.layered_format_line_fail_vertical),
        }
        report["layered_format_fail_examples"] = list(self.m.layered_format_fail_examples)
        report["layered_bootstrap_threshold_fallback_attempts"] = float(
            self.m.layered_bootstrap_threshold_fallback_attempts
        )
        report["layered_bootstrap_threshold_fallback_successes"] = float(
            self.m.layered_bootstrap_threshold_fallback_successes
        )

    def attach_pipeline_metrics(
        self, report: Dict[str, object], snap: Mapping[str, object]
    ) -> None:
        """Attach pipeline-specific metrics to report.

        Args:
            report: Report dictionary to update
            snap: Pipeline stats snapshot
        """
        report["pipeline_captured"] = _as_float(snap.get("captured", 0))
        report["pipeline_decode_ok"] = _as_float(snap.get("decode_ok", 0))
        report["pipeline_decode_fail"] = _as_float(snap.get("decode_fail", 0))
        report["pipeline_decode_exceptions"] = _as_float(snap.get("decode_exceptions", 0))
        report["pipeline_assembled"] = _as_float(snap.get("assembled", 0))
        report["pipeline_assembled_bytes"] = _as_float(snap.get("assembled_bytes", 0))
        report["pipeline_dropped_queue_full"] = _as_float(snap.get("dropped_queue_full", 0))
        report["pipeline_dropped_result_queue_full"] = _as_float(
            snap.get("dropped_result_queue_full", 0)
        )
        report["pipeline_last_failure_error"] = str(snap.get("last_decode_error", ""))
        report["pipeline_last_failure_class"] = str(snap.get("last_failure_class", ""))
        report["pipeline_failure_count_header"] = _as_float(snap.get("failure_count_header", 0))
        report["pipeline_failure_count_payload"] = _as_float(snap.get("failure_count_payload", 0))
        report["pipeline_failure_count_locator"] = _as_float(snap.get("failure_count_locator", 0))
        report["pipeline_failure_count_unknown"] = _as_float(snap.get("failure_count_unknown", 0))

        # Geometry locking metrics
        report["lock_acquire_to_locked"] = _as_float(snap.get("lock_acquire_to_locked", 0))
        report["lock_locked_to_acquire"] = _as_float(snap.get("lock_locked_to_acquire", 0))
        report["locked_decode_fail_streak_max"] = _as_float(
            snap.get("locked_decode_fail_streak_max", 0)
        )
        report["geometry_reuse_success_count"] = _as_float(
            snap.get("geometry_reuse_success_count", 0)
        )
        report["geometry_reuse_fail_count"] = _as_float(snap.get("geometry_reuse_fail_count", 0))
        report["reacquire_attempt_count"] = _as_float(snap.get("reacquire_attempt_count", 0))
        report["reacquire_success_count"] = _as_float(snap.get("reacquire_success_count", 0))
        report["reacquire_fail_count"] = _as_float(snap.get("reacquire_fail_count", 0))
        report["locked_geometry_age_max"] = _as_float(snap.get("locked_geometry_age_max", 0))
        report["homography_rmse_reused_last"] = _as_float(
            snap.get("homography_rmse_reused_last", 0.0)
        )
        report["homography_rmse_reacquired_last"] = _as_float(
            snap.get("homography_rmse_reacquired_last", 0.0)
        )

        # Layered protocol metrics from pipeline
        if self.m.protocol == "layered":
            report["layered_control_path_version"] = _as_float(
                snap.get("layered_control_path_version", 4)
            )
            report["layered_core_header_raw_bytes"] = _as_float(
                snap.get("layered_core_header_raw_bytes", 0)
            )
            report["layered_core_header_coded_bytes"] = _as_float(
                snap.get("layered_core_header_coded_bytes", 0)
            )
            report["layered_core_header_ecc_nsym"] = _as_float(
                snap.get("layered_core_header_ecc_nsym", 0)
            )
            report["layered_core_header_attempt_count"] = _as_float(
                snap.get("layered_core_header_attempt_count", 0)
            )
            report["layered_core_header_threshold_avg"] = _as_float(
                snap.get("layered_core_header_threshold_avg", 0.0)
            )
            report["layered_core_header_vote_margin_min"] = _as_float(
                snap.get("layered_core_header_vote_margin_min", 0.0)
            )
            report["layered_core_header_vote_margin_avg"] = _as_float(
                snap.get("layered_core_header_vote_margin_avg", 0.0)
            )

    def attach_control_plane_state(self, report: Dict[str, object], assembler) -> None:
        """Attach control plane state to report.

        Args:
            report: Report dictionary to update
            assembler: ChunkAssembler instance
        """
        report["control_plane_kinds"] = sorted(list(assembler.control_items.keys()))
        if assembler.session_info is not None:
            report["control_session"] = dict(assembler.session_info)
        if assembler.layout_info is not None:
            report["control_layout"] = dict(assembler.layout_info)
        if assembler.generation_info is not None:
            report["control_generation"] = dict(assembler.generation_info)
        report["control_generations_seen"] = sorted(int(k) for k in assembler.generations.keys())

    def attach_missing_chunks_state(
        self, report: Dict[str, object], assembler
    ) -> None:
        """Attach missing chunks information to report.

        Args:
            report: Report dictionary to update
            assembler: ChunkAssembler instance
        """
        missing = assembler.missing_chunks()
        report["missing_chunk_count"] = len(missing)
        report["missing_chunk_ids"] = sorted(missing)

    def attach_startup_state(self, report: Dict[str, object]) -> None:
        """Attach startup metrics to report.

        Args:
            report: Report dictionary to update
        """
        report["startup_sync_frames_decoded"] = float(self.m.startup_sync_frames_decoded)
        report["startup_control_frames_decoded"] = float(self.m.startup_control_frames_decoded)
        report["decoded_new_chunks"] = float(self.m.decoded_new_chunks)
        report["decoded_duplicate_chunks"] = float(self.m.decoded_duplicate_chunks)

    def sync_transfer_stats_from_pipeline(self, snap: Mapping[str, object]) -> None:
        """Sync transfer stats from pipeline snapshot.

        Args:
            snap: Pipeline stats snapshot
        """
        self.stats.total_frames = _as_int(snap.get("captured", 0))
        self.stats.valid_frames = _as_int(snap.get("decode_ok", 0))
        self.stats.bad_frames = _as_int(snap.get("decode_fail", 0))
