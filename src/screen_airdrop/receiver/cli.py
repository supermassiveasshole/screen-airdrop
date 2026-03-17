# pyright: reportArgumentType=false, reportOperatorIssue=false
"""Realtime/replay receiver CLI with V2 auto locator and manual ROI fallback."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, cast

import numpy as np

from screen_airdrop.common.control_plane import (
    control_family_for_kind,
    control_kind_from_wire_chunk_id,
    decode_generation_control,
    decode_layout_bootstrap,
    decode_session_bootstrap,
)
from screen_airdrop.common.ecc_rs import LAYERED_BOOTSTRAP_RS
from screen_airdrop.common.protocol_basic import FRAME_DATA
from screen_airdrop.common.protocol_layered import layered_bootstrap_payload_size_bytes
from screen_airdrop.receiver.assembler import ChunkAssembler
from screen_airdrop.receiver.capture_mss import ScreenCapture, get_monitor_region
from screen_airdrop.receiver.decoder_basic import decode_frame_basic
from screen_airdrop.receiver.decoder_compact import decode_frame_compact
from screen_airdrop.receiver.decoder_gray4 import decode_frame_gray4
from screen_airdrop.receiver.decoder_layered import (
    decode_frame_layered,
    decode_frame_layered_with_geometry,
)
from screen_airdrop.receiver.detector_basic import _bbox_from_non_black, detect_symbol_bbox
from screen_airdrop.receiver.frame_replay_source import FrameReplaySource
from screen_airdrop.receiver.locator_basic import LocateError as LocateErrorV31
from screen_airdrop.receiver.locator_basic import LocatorConfig, locate_frame
from screen_airdrop.receiver.protocol_adapter_layered import LayeredProtocolDecoder
from screen_airdrop.receiver.protocol_observability import make_protocol_report_adapter
from screen_airdrop.receiver.restore import restore_payload
from screen_airdrop.receiver.roi_policy import RoiPolicy
from screen_airdrop.receiver.roi_profile import load_profile, save_profile
from screen_airdrop.receiver.roi_selector import select_region
from screen_airdrop.receiver.screen_live_runtime import ScreenLiveRuntime
from screen_airdrop.receiver.stats import TransferStats
from screen_airdrop.receiver.window_locator import resolve_window_region

# Debug utilities
from screen_airdrop.receiver.debug import DebugSnapshotManager

# ROI utilities
from screen_airdrop.receiver.roi import RoiManager, ensure_roi_valid

# Configuration
from screen_airdrop.receiver.config import ReceiverConfig

# Reporting
from screen_airdrop.receiver.reporting import MetricsState, ReportBuilder


def _parse_region(raw: Optional[str]) -> Optional[Tuple[int, int, int, int]]:
    if not raw:
        return None
    parts = [int(p.strip()) for p in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("region/roi must be x,y,w,h")
    return parts[0], parts[1], parts[2], parts[3]


def _parse_module_grid(raw: str) -> Tuple[int, int]:
    try:
        gw, gh = [int(p) for p in raw.lower().split("x")]
    except Exception as exc:
        raise ValueError("module-grid must be like 160x96: {0}".format(exc))
    if gw < 64 or gh < 48:
        raise ValueError("module-grid too small")
    return gw, gh


# Protocol geometry configuration
PROTOCOL_GEOMETRY_MAP = {
    "compact": (1, 7),
    "gray4": (1, 7),
    "layered": (1, 7),
    "basic": (2, 9),
}


def _protocol_geometry(protocol: str) -> Tuple[int, int]:
    """Get guard_band and corner_size for protocol."""
    return PROTOCOL_GEOMETRY_MAP.get(protocol, (2, 9))


def _write_report(path: Optional[str], report: dict) -> None:
    if not path:
        return
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def _classify_gray4_decode_failure(decode_error: Optional[str]) -> str:
    raw = "" if decode_error is None else str(decode_error).strip().lower()
    if not raw:
        return ""
    if "payload rs decode failed" in raw or "payload crc mismatch" in raw or "crc mismatch" in raw:
        return "payload"
    if "header rs decode failed" in raw or "bad v3 magic" in raw or "format parity mismatch" in raw:
        return "header"
    if "locator" in raw or "no_finder" in raw or "finder" in raw:
        return "locator"
    return "unknown"


def _as_int(value: object, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(value)
    except Exception:
        return default


def _as_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except Exception:
        return default


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: object) -> List[object]:
    return list(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="screen-airdrop receiver")
    # Source configuration
    parser.add_argument(
        "--source", choices=["screen", "replay"], default="screen", help="capture source"
    )
    parser.add_argument(
        "--window-title", default=None, help="window title to locate (screen source)"
    )
    parser.add_argument("--monitor-index", type=int, default=1, help="mss monitor index (1-based)")
    parser.add_argument(
        "--frames-dir", default=None, help="directory with captured frames (replay source)"
    )

    # Protocol and grid configuration (information/robustness parameters)
    parser.add_argument(
        "--protocol",
        choices=["basic", "compact", "gray4", "layered"],
        default="basic",
        help="protocol name",
    )
    parser.add_argument(
        "--module-grid", default="160x96", help="module grid size (must match sender)"
    )
    parser.add_argument(
        "--block-size",
        default="6",
        help="legacy compatibility option; ignored by the basic protocol decoder",
    )

    # ROI configuration (simplified from 7 parameters to 2)
    parser.add_argument(
        "--roi", default=None, help="manual ROI as x,y,w,h (if not set, use auto detection)"
    )
    parser.add_argument(
        "--region",
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--roi-interactive", action="store_true", help="enable interactive ROI selection"
    )
    parser.add_argument("--select-region", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--roi-profile", default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--roi-mode",
        choices=["auto", "manual", "auto_then_manual"],
        default="auto_then_manual",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--manual-roi-pad-px", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--manual-max-retries", type=int, default=1, help=argparse.SUPPRESS)
    parser.add_argument("--auto-fail-threshold", type=int, default=5, help=argparse.SUPPRESS)
    parser.add_argument(
        "--detect-mode",
        choices=["full", "track", "roi"],
        default="track",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--track-margin-px", type=int, default=96, help=argparse.SUPPRESS)
    parser.add_argument(
        "--locator-engine",
        choices=["new", "legacy", "auto"],
        default="auto",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--locator-confidence-threshold",
        type=float,
        default=0.55,
        help=argparse.SUPPRESS,
    )

    # Output configuration
    parser.add_argument(
        "--output-dir", default="./recovered", help="output directory for recovered files"
    )
    parser.add_argument("--report-json", default=None, help="path to write JSON report")

    # Timing configuration
    parser.add_argument(
        "--max-idle-seconds", type=int, default=30, help="max idle time before exit"
    )
    parser.add_argument("--max-seconds", type=int, default=0, help="max total time (0=unlimited)")
    parser.add_argument(
        "--stats-interval", type=float, default=1.0, help="stats update interval in seconds"
    )
    parser.add_argument(
        "--capture-fps",
        type=float,
        default=30.0,
        help="target capture FPS (screen source only)",
    )

    # Debug configuration
    parser.add_argument("--debug-dir", default=None, help="dump debug snapshots to this directory")
    parser.add_argument(
        "--debug-interval", type=float, default=1.0, help="seconds between debug snapshots"
    )
    parser.add_argument(
        "--debug-max-frames", type=int, default=30, help="max debug snapshots to write"
    )

    # Advanced configuration
    parser.add_argument(
        "--decode-workers",
        type=int,
        default=0,
        help="number of parallel decode workers (0=auto)",
    )
    parser.add_argument(
        "--prep-process",
        type=int,
        default=0,
        help="screen live runtime prep mode: 0=async in coordinator, 1=dedicated prep process",
    )
    parser.add_argument(
        "--frame-queue-size",
        type=int,
        default=32,
        help="pipeline frame queue size (screen source only)",
    )
    parser.add_argument(
        "--result-queue-size",
        type=int,
        default=256,
        help="pipeline result queue size (screen source only)",
    )
    parser.add_argument(
        "--capture-dump-dir",
        default=None,
        help="dump pipeline-captured frames for later replay (screen source only)",
    )
    parser.add_argument(
        "--capture-dump-max-frames",
        type=int,
        default=0,
        help="max pipeline-captured frames to dump (0=disabled)",
    )
    return parser


def _build_source(config: ReceiverConfig, region):
    if config.is_replay_mode():
        if not config.frames_dir:
            raise ValueError("--frames-dir is required when --source replay")
        return FrameReplaySource(frames_dir=config.frames_dir)

    capture_region = None
    # Manual ROI mode should crop at capture stage to avoid coordinate drift and
    # selector-overlay interference in subsequent decode frames.
    if config.roi_mode == "manual" and region is not None:
        capture_region = region

    return ScreenCapture(
        window_title=config.window_title,
        region=capture_region,
        monitor_index=config.monitor_index,
    )


def _print_stats(snapshot: dict, missing: Optional[int]) -> None:
    print(
        "raw_fps={0:.2f} valid_fps={1:.2f} goodput_KiBps={2:.2f} bad_frame_rate={3:.4f} locator_fail_rate={4:.4f} missing={5}".format(
            snapshot["raw_frame_rate_fps"],
            snapshot["valid_frame_rate_fps"],
            snapshot["goodput_kibps"],
            snapshot["bad_frame_rate"],
            snapshot.get("locator_fail_rate", 0.0),
            "?" if missing is None else missing,
        )
    )


def _build_pipeline_seed_roi_local(
    source: object,
    forced_roi_abs: Optional[Tuple[int, int, int, int]],
) -> Optional[Tuple[int, int, int, int]]:
    if forced_roi_abs is None:
        return None
    try:
        monitor_index = int(getattr(source, "monitor_index"))
        window_title = getattr(source, "window_title")
        explicit_region = getattr(source, "region")
        monitor_region = get_monitor_region(monitor_index)

        capture_region = resolve_window_region(
            window_title=window_title,
            explicit_region=explicit_region,
            monitor_region=monitor_region,
        )
        frame_shape = (int(capture_region[3]), int(capture_region[2]), 3)
        roi_mgr = RoiManager(capture_region)
        return roi_mgr.abs_to_local(forced_roi_abs, frame_shape)
    except Exception:
        return None


def _should_use_pipeline(
    *,
    source: str,
    protocol: str,
    debug_dir: Optional[str],
    needs_runtime_roi_selection: bool,
) -> bool:
    return (
        source == "screen"
        and protocol in ("basic", "compact", "gray4", "layered")
        and not needs_runtime_roi_selection
        and not debug_dir
    )


def main(argv=None):
    args = build_parser().parse_args(argv)
    config = ReceiverConfig.from_args(args)
    config.validate()
    roi_policy = RoiPolicy.from_args(args)
    roi_policy.apply_to_args(args)
    if config.source == "screen" and config.window_title and not (config.roi or config.region):
        print(
            "warning: --window-title is currently not used for real window lookup; "
            "capture will fallback to full monitor. "
            "Use --roi x,y,w,h or --roi-interactive for reliable decode."
        )

    block_size_candidates = config.get_block_size_candidates()
    selected_block_size = None  # type: Optional[int]
    grid_w, grid_h = config.get_grid_size()
    grid_candidates = [(grid_w, grid_h), (160, 96), (176, 100), (192, 108), (224, 126)]
    uniq = []
    seen = set()
    for g in grid_candidates:
        if g in seen:
            continue
        seen.add(g)
        uniq.append(g)
    grid_candidates = uniq

    cli_roi = _parse_region(config.roi) or _parse_region(config.region)
    profile_roi = load_profile(config.roi_profile) if config.roi_profile else None

    forced_roi = cli_roi or profile_roi
    if forced_roi is not None:
        forced_roi = ensure_roi_valid(forced_roi)

    if roi_policy.requires_manual_roi(forced_roi=forced_roi):
        raise ValueError("manual roi-mode requires --roi/--roi-profile or --roi-interactive")

    stats = TransferStats()
    stats.set_roi_mode(roi_policy.report_mode)
    if (
        config.source == "screen"
        and roi_policy.mode == "manual"
        and forced_roi is None
        and roi_policy.interactive
    ):
        stats.mark_manual_select_attempt()
        selected = select_region(get_monitor_region(config.monitor_index))
        if selected is None:
            raise RuntimeError("manual roi selection canceled")
        forced_roi = ensure_roi_valid(selected)
        stats.mark_manual_roi(switched=False)
        if config.roi_profile:
            save_profile(config.roi_profile, forced_roi, config.monitor_index)

    source = _build_source(config, forced_roi)
    if config.debug_dir and isinstance(source, ScreenCapture):
        # Debug mode should not be throttled by frame dedup; otherwise
        # mostly-static captures may produce almost no snapshots.
        source.frame_diff_threshold = 0.0
    if config.debug_dir:
        os.makedirs(config.debug_dir, exist_ok=True)
        print(
            "debug enabled: dir={0} interval={1}s max_frames={2}".format(
                config.debug_dir,
                config.debug_interval,
                config.debug_max_frames,
            )
        )
    assembler = ChunkAssembler()

    threshold = None
    start = time.time()
    last_good = start
    next_stats_ts = start + max(0.1, config.stats_interval)

    final_report = None  # type: Optional[dict]
    auto_fail_count = 0
    manual_attempts = 0
    frame_index = 0

    # Initialize debug snapshot manager
    debug_manager = None
    if config.debug_dir:
        debug_manager = DebugSnapshotManager(
            debug_dir=config.debug_dir,
            debug_max_frames=config.debug_max_frames,
            debug_interval=config.debug_interval,
        )

    last_decode_error = None  # type: Optional[str]
    last_gray4_failure_error = None  # type: Optional[str]
    last_gray4_failure_class = ""
    gray4_failure_counts = {"header": 0, "payload": 0, "locator": 0, "unknown": 0}
    layered_failure_counts = {
        "control_prefix": 0,
        "format": 0,
        "bootstrap_rs": 0,
        "bootstrap_crc": 0,
        "body_rs": 0,
        "body_crc": 0,
    }
    layered_bootstrap_threshold_fallback_attempts = 0
    layered_bootstrap_threshold_fallback_successes = 0
    layered_format_attempt_count = 0
    layered_format_fallback_attempts = 0
    layered_format_fallback_successes = 0
    layered_format_primary_threshold_sum = 0.0
    layered_format_primary_threshold_count = 0
    layered_format_fallback_threshold_sum = 0.0
    layered_format_fallback_threshold_count = 0
    layered_format_vote_margin_sum = 0.0
    layered_format_vote_margin_count = 0
    layered_format_vote_margin_min = 0.0
    layered_format_mask_fail_counts = {}  # type: Dict[str, int]
    layered_format_bit_fail_counts = [0] * 80
    layered_format_line_fail_horizontal = 0
    layered_format_line_fail_vertical = 0
    layered_format_fail_examples = []  # type: List[Dict[str, object]]
    first_valid_frame_ts = None  # type: Optional[float]
    first_data_frame_ts = None  # type: Optional[float]
    first_new_chunk_ts = None  # type: Optional[float]
    startup_sync_frames_decoded = 0
    startup_control_frames_decoded = 0
    decoded_new_chunks = 0
    decoded_duplicate_chunks = 0
    last_v3_meta = None
    last_v31_meta = None
    protocol_path_used = config.protocol
    decode_attempt_total = 0
    fallback_hits = 0
    locator_new_fail_reason = ""
    locator_new_elapsed_ms = 0.0
    locator_legacy_used = False
    locator_legacy_elapsed_ms = 0.0
    bbox_jitter_sum = 0.0
    bbox_jitter_count = 0
    prev_bbox = None  # type: Optional[Tuple[int, int, int, int]]
    last_det_bbox = None  # type: Optional[Tuple[int, int, int, int]]
    last_det_confidence = 0.0
    layered_failure_trace = None  # type: Optional[Dict[str, object]]
    protocol_report_adapter = make_protocol_report_adapter(config.protocol)
    decode_time_sum = 0.0
    decode_time_count = 0
    replay_mode = config.source == "replay"
    v3_track_roi = None
    v3_fail_streak = 0
    v3_mode = "full" if (config.detect_mode == "full" or replay_mode) else "track"
    layered_locked_geometry = None
    layered_locked_fail_streak = 0
    layered_locked_geometry_age = 0
    layered_locked_fail_reacquire_threshold = 5
    lock_decode_mode_geometry_reuse = 0
    lock_decode_mode_reacquire_locator = 0
    geometry_reuse_success_count = 0
    geometry_reuse_fail_count = 0
    reacquire_attempt_count = 0
    reacquire_success_count = 0
    reacquire_fail_count = 0
    locked_geometry_age_max = 0
    homography_rmse_reused_last = 0.0
    homography_rmse_reacquired_last = 0.0

    def _attach_v3_metrics(report: Dict[str, object]) -> None:
        if protocol_path_used:
            report["protocol_path_used"] = protocol_path_used
        report["decode_attempts_per_frame"] = float(decode_attempt_total) / float(
            max(1, stats.total_frames)
        )
        report["fallback_ratio"] = float(fallback_hits) / float(max(1, stats.valid_frames))
        report["homography_stability"] = (
            bbox_jitter_sum / float(max(1, bbox_jitter_count)) if bbox_jitter_count > 0 else 0.0
        )
        report["avg_decode_ms"] = (decode_time_sum / float(max(1, decode_time_count))) * 1000.0
        if debug_manager:
            report["avg_debug_dump_ms"] = (
                debug_manager.debug_time_sum / float(max(1, debug_manager.debug_time_count))
            ) * 1000.0
        else:
            report["avg_debug_dump_ms"] = 0.0
        report["new_fail_reason"] = locator_new_fail_reason
        report["new_elapsed_ms"] = float(locator_new_elapsed_ms)
        report["legacy_used"] = 1.0 if locator_legacy_used else 0.0
        report["legacy_elapsed_ms"] = float(locator_legacy_elapsed_ms)

    def _attach_gray4_state(
        report: Dict[str, object],
        *,
        failure_error: Optional[str],
        failure_class: str,
        success_meta: Optional[object],
        failure_counts: Optional[Mapping[str, object]] = None,
    ) -> None:
        if config.protocol not in ("gray4", "layered"):
            return
        report["gray4_last_failure_error"] = "" if failure_error is None else str(failure_error)
        report["gray4_last_failure_class"] = str(failure_class or "")
        if failure_counts is not None:
            report["gray4_failure_counts"] = {
                "header": int(failure_counts.get("header", 0) or 0),
                "payload": int(failure_counts.get("payload", 0) or 0),
                "locator": int(failure_counts.get("locator", 0) or 0),
                "unknown": int(failure_counts.get("unknown", 0) or 0),
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
        if config.protocol == "layered":
            report["layered_control_path_version"] = 4.0
            report["layered_core_header_raw_bytes"] = float(layered_bootstrap_payload_size_bytes())
            report["layered_core_header_coded_bytes"] = float(
                layered_bootstrap_payload_size_bytes() + int(LAYERED_BOOTSTRAP_RS.nsym)
            )
            report["layered_core_header_ecc_nsym"] = float(LAYERED_BOOTSTRAP_RS.nsym)
            report["layered_core_header_attempt_count"] = float(layered_format_attempt_count)
            report["layered_core_header_threshold_avg"] = (
                0.0
                if layered_format_primary_threshold_count <= 0
                else layered_format_primary_threshold_sum / float(layered_format_primary_threshold_count)
            )
            report["layered_core_header_vote_margin_min"] = float(layered_format_vote_margin_min)
            report["layered_core_header_vote_margin_avg"] = (
                0.0
                if layered_format_vote_margin_count <= 0
                else layered_format_vote_margin_sum / float(layered_format_vote_margin_count)
            )
            report["layered_core_header_erasure_symbol_count_avg"] = 0.0
            report["layered_core_header_erasure_symbol_count_max"] = 0.0
            report["layered_core_header_errata_corrected_avg"] = 0.0
            report["layered_core_header_errata_corrected_max"] = 0.0
            report["layered_core_header_rs_fail_count"] = float(layered_failure_counts["bootstrap_rs"])
            report["layered_core_header_crc_fail_count"] = float(layered_failure_counts["bootstrap_crc"])
            report["layered_core_header_fail_examples"] = list(layered_format_fail_examples)
            report["layered_control_prefix_fail_count"] = 0.0
            report["layered_format_fail_count"] = 0.0
            report["layered_bootstrap_attempt_count"] = float(layered_format_attempt_count)
            report["layered_bootstrap_threshold_avg"] = (
                0.0
                if layered_format_primary_threshold_count <= 0
                else layered_format_primary_threshold_sum / float(layered_format_primary_threshold_count)
            )
            report["layered_bootstrap_vote_margin_min"] = float(layered_format_vote_margin_min)
            report["layered_bootstrap_vote_margin_avg"] = (
                0.0
                if layered_format_vote_margin_count <= 0
                else layered_format_vote_margin_sum / float(layered_format_vote_margin_count)
            )
            report["layered_bootstrap_bit_fail_counts"] = list(layered_format_bit_fail_counts)
            report["layered_bootstrap_fail_examples"] = list(layered_format_fail_examples)
            report["layered_bootstrap_rs_fail_count"] = float(layered_failure_counts["bootstrap_rs"])
            report["layered_bootstrap_crc_fail_count"] = float(layered_failure_counts["bootstrap_crc"])
            report["layered_body_rs_fail_count"] = float(layered_failure_counts["body_rs"])
            report["layered_body_crc_fail_count"] = float(layered_failure_counts["body_crc"])
            report["layered_format_attempt_count"] = float(layered_format_attempt_count)
            report["layered_format_fallback_attempts"] = float(layered_format_fallback_attempts)
            report["layered_format_fallback_successes"] = float(layered_format_fallback_successes)
            report["layered_format_primary_threshold_avg"] = (
                0.0
                if layered_format_primary_threshold_count <= 0
                else layered_format_primary_threshold_sum / float(layered_format_primary_threshold_count)
            )
            report["layered_format_fallback_threshold_avg"] = (
                0.0
                if layered_format_fallback_threshold_count <= 0
                else layered_format_fallback_threshold_sum / float(layered_format_fallback_threshold_count)
            )
            report["layered_format_vote_margin_min"] = float(layered_format_vote_margin_min)
            report["layered_format_vote_margin_avg"] = (
                0.0
                if layered_format_vote_margin_count <= 0
                else layered_format_vote_margin_sum / float(layered_format_vote_margin_count)
            )
            report["layered_format_mask_fail_counts"] = dict(layered_format_mask_fail_counts)
            report["layered_format_bit_fail_counts"] = list(layered_format_bit_fail_counts)
            report["layered_format_line_fail_counts"] = {
                "horizontal": int(layered_format_line_fail_horizontal),
                "vertical": int(layered_format_line_fail_vertical),
            }
            report["layered_format_fail_examples"] = list(layered_format_fail_examples)
            report["layered_bootstrap_threshold_fallback_attempts"] = float(
                layered_bootstrap_threshold_fallback_attempts
            )
            report["layered_bootstrap_threshold_fallback_successes"] = float(
                layered_bootstrap_threshold_fallback_successes
            )

    def _attach_protocol_debug(report: Dict[str, object]) -> None:
        report.update(protocol_report_adapter.finalize_summary())

    def _sync_transfer_stats_from_pipeline(snap: Mapping[str, object]) -> None:
        stats.total_frames = _as_int(snap.get("captured", 0))
        stats.valid_frames = _as_int(snap.get("decode_ok", 0))
        stats.bad_frames = _as_int(snap.get("decode_fail", 0))

    def _attach_pipeline_metrics(
        report: Dict[str, object], snap: Mapping[str, object]
    ) -> None:
        report["pipeline_captured"] = _as_float(snap.get("captured", 0))
        report["pipeline_decode_ok"] = _as_float(snap.get("decode_ok", 0))
        report["pipeline_decode_fail"] = _as_float(snap.get("decode_fail", 0))
        report["pipeline_decode_exceptions"] = _as_float(snap.get("decode_exceptions", 0))
        report["pipeline_assembled"] = _as_float(snap.get("assembled", 0))
        report["pipeline_assembled_bytes"] = _as_float(snap.get("assembled_bytes", 0))
        report["pipeline_dropped_frame_queue_full"] = _as_float(snap.get("dropped_queue_full", 0))
        report["pipeline_dropped_result_queue_full"] = _as_float(snap.get("dropped_result_queue_full", 0))
        report["pipeline_duplicate_frames"] = _as_float(snap.get("duplicate_frames", 0))
        report["pipeline_capture_grab_time_ms"] = _as_float(snap.get("capture_grab_time_ms", 0.0))
        report["pipeline_capture_copy_time_ms"] = _as_float(snap.get("capture_copy_time_ms", 0.0))
        report["pipeline_capture_dedup_time_ms"] = _as_float(snap.get("capture_dedup_time_ms", 0.0))
        report["pipeline_capture_grab_ops"] = _as_float(snap.get("capture_grab_ops", 0))
        report["pipeline_capture_copy_ops"] = _as_float(snap.get("capture_copy_ops", 0))
        report["pipeline_capture_dedup_ops"] = _as_float(snap.get("capture_dedup_ops", 0))
        report["pipeline_ipc_recv_time_ms"] = _as_float(snap.get("ipc_recv_time_ms", 0.0))
        report["pipeline_ipc_recv_ops"] = _as_float(snap.get("ipc_recv_ops", 0))
        report["pipeline_fingerprint_time_ms"] = _as_float(snap.get("fingerprint_time_ms", 0.0))
        report["pipeline_fingerprint_ops"] = _as_float(snap.get("fingerprint_ops", 0))
        report["pipeline_materialize_time_ms"] = _as_float(snap.get("materialize_time_ms", 0.0))
        report["pipeline_materialize_ops"] = _as_float(snap.get("materialize_ops", 0))
        report["pipeline_dump_time_ms"] = _as_float(snap.get("dump_time_ms", 0.0))
        report["pipeline_dump_ops"] = _as_float(snap.get("dump_ops", 0))
        report["pipeline_dump_frames"] = _as_float(snap.get("dump_frames", 0))
        report["pipeline_dropped_raw_queue_full"] = _as_float(snap.get("dropped_raw_queue_full", 0))
        report["pipeline_dropped_prep_queue_full"] = _as_float(snap.get("dropped_prep_queue_full", 0))
        report["pipeline_dropped_dump_queue_full"] = _as_float(snap.get("dropped_dump_queue_full", 0))
        report["pipeline_shared_memory_bytes_peak"] = _as_float(snap.get("shared_memory_bytes_peak", 0))
        report["time_to_first_valid_frame_s"] = _as_float(snap.get("time_to_first_valid_frame_s", 0.0))
        report["time_to_first_data_frame_s"] = _as_float(snap.get("time_to_first_data_frame_s", 0.0))
        report["time_to_first_new_chunk_s"] = _as_float(snap.get("time_to_first_new_chunk_s", 0.0))
        report["startup_sync_frames_decoded"] = _as_float(snap.get("startup_sync_frames_decoded", 0))
        report["startup_control_frames_decoded"] = _as_float(snap.get("startup_control_frames_decoded", 0))
        report["decoded_new_chunks"] = _as_float(snap.get("decoded_new_chunks", 0))
        report["decoded_duplicate_chunks"] = _as_float(snap.get("decoded_duplicate_chunks", 0))
        protocol_debug = snap.get("protocol_debug")
        if isinstance(protocol_debug, dict):
            report["protocol_debug"] = dict(_as_mapping(protocol_debug))
        report["lock_state_transitions"] = {
            "acquire_to_locked": _as_int(snap.get("lock_acquire_to_locked", 0)),
            "locked_to_acquire": _as_int(snap.get("lock_locked_to_acquire", 0)),
        }
        report["locked_decode_fail_streak_max"] = _as_float(snap.get("locked_decode_fail_streak_max", 0))
        lock_decode_mode_counts = snap.get("lock_decode_mode_counts")
        if isinstance(lock_decode_mode_counts, Mapping):
            report["lock_decode_mode_counts"] = {
                "geometry_reuse": _as_int(lock_decode_mode_counts.get("geometry_reuse", 0)),
                "reacquire_locator": _as_int(lock_decode_mode_counts.get("reacquire_locator", 0)),
            }
        report["geometry_reuse_success_count"] = _as_float(snap.get("geometry_reuse_success_count", 0))
        report["geometry_reuse_fail_count"] = _as_float(snap.get("geometry_reuse_fail_count", 0))
        report["reacquire_attempt_count"] = _as_float(snap.get("reacquire_attempt_count", 0))
        report["reacquire_success_count"] = _as_float(snap.get("reacquire_success_count", 0))
        report["reacquire_fail_count"] = _as_float(snap.get("reacquire_fail_count", 0))
        report["locked_geometry_age_max"] = _as_float(snap.get("locked_geometry_age_max", 0))
        report["homography_rmse_reused_last"] = _as_float(snap.get("homography_rmse_reused_last", 0.0))
        report["homography_rmse_reacquired_last"] = _as_float(snap.get("homography_rmse_reacquired_last", 0.0))
        if config.protocol == "layered":
            report["layered_control_path_version"] = _as_float(snap.get("layered_control_path_version", 4))
            report["layered_core_header_raw_bytes"] = _as_float(snap.get("layered_core_header_raw_bytes", 0))
            report["layered_core_header_coded_bytes"] = _as_float(snap.get("layered_core_header_coded_bytes", 0))
            report["layered_core_header_ecc_nsym"] = _as_float(snap.get("layered_core_header_ecc_nsym", 0))
            report["layered_core_header_attempt_count"] = _as_float(snap.get("layered_core_header_attempt_count", 0))
            report["layered_core_header_threshold_avg"] = _as_float(snap.get("layered_core_header_threshold_avg", 0.0))
            report["layered_core_header_vote_margin_min"] = _as_float(snap.get("layered_core_header_vote_margin_min", 0.0))
            report["layered_core_header_vote_margin_avg"] = _as_float(snap.get("layered_core_header_vote_margin_avg", 0.0))
            report["layered_core_header_erasure_symbol_count_avg"] = _as_float(snap.get("layered_core_header_erasure_symbol_count_avg", 0.0))
            report["layered_core_header_erasure_symbol_count_max"] = _as_float(snap.get("layered_core_header_erasure_symbol_count_max", 0.0))
            report["layered_core_header_errata_corrected_avg"] = _as_float(snap.get("layered_core_header_errata_corrected_avg", 0.0))
            report["layered_core_header_errata_corrected_max"] = _as_float(snap.get("layered_core_header_errata_corrected_max", 0.0))
            report["layered_core_header_rs_fail_count"] = _as_float(snap.get("layered_core_header_rs_fail_count", 0))
            report["layered_core_header_crc_fail_count"] = _as_float(snap.get("layered_core_header_crc_fail_count", 0))
            report["layered_core_header_fail_examples"] = _as_list(snap.get("layered_core_header_fail_examples", []))
            report["layered_control_prefix_fail_count"] = 0.0
            report["layered_format_fail_count"] = 0.0
            report["layered_bootstrap_attempt_count"] = _as_float(snap.get("layered_bootstrap_attempt_count", 0))
            report["layered_bootstrap_threshold_avg"] = _as_float(snap.get("layered_bootstrap_threshold_avg", 0.0))
            report["layered_bootstrap_vote_margin_min"] = _as_float(snap.get("layered_bootstrap_vote_margin_min", 0.0))
            report["layered_bootstrap_vote_margin_avg"] = _as_float(snap.get("layered_bootstrap_vote_margin_avg", 0.0))
            report["layered_bootstrap_bit_fail_counts"] = _as_list(snap.get("layered_bootstrap_bit_fail_counts", []))
            report["layered_bootstrap_fail_examples"] = _as_list(snap.get("layered_bootstrap_fail_examples", []))
            report["layered_bootstrap_rs_fail_count"] = _as_float(snap.get("layered_bootstrap_rs_fail_count", 0))
            report["layered_bootstrap_crc_fail_count"] = _as_float(snap.get("layered_bootstrap_crc_fail_count", 0))
            report["layered_body_rs_fail_count"] = _as_float(snap.get("layered_body_rs_fail_count", 0))
            report["layered_body_crc_fail_count"] = _as_float(snap.get("layered_body_crc_fail_count", 0))
            report["layered_bootstrap_threshold_fallback_attempts"] = _as_float(snap.get("layered_bootstrap_threshold_fallback_attempts", 0))
            report["layered_bootstrap_threshold_fallback_successes"] = _as_float(snap.get("layered_bootstrap_threshold_fallback_successes", 0))
            report["layered_format_attempt_count"] = _as_float(snap.get("layered_format_attempt_count", 0))
            report["layered_format_fallback_attempts"] = _as_float(snap.get("layered_format_fallback_attempts", 0))
            report["layered_format_fallback_successes"] = _as_float(snap.get("layered_format_fallback_successes", 0))
            report["layered_format_primary_threshold_avg"] = _as_float(snap.get("layered_format_primary_threshold_avg", 0.0))
            report["layered_format_fallback_threshold_avg"] = _as_float(snap.get("layered_format_fallback_threshold_avg", 0.0))
            report["layered_format_vote_margin_min"] = _as_float(snap.get("layered_format_vote_margin_min", 0.0))
            report["layered_format_vote_margin_avg"] = _as_float(snap.get("layered_format_vote_margin_avg", 0.0))
            report["layered_format_mask_fail_counts"] = dict(_as_mapping(snap.get("layered_format_mask_fail_counts", {})))
            report["layered_format_bit_fail_counts"] = _as_list(snap.get("layered_format_bit_fail_counts", []))
            report["layered_format_line_fail_counts"] = dict(_as_mapping(snap.get("layered_format_line_fail_counts", {})))
            report["layered_format_fail_examples"] = _as_list(snap.get("layered_format_fail_examples", []))

    def _classify_layered_decode_failure_detail(decode_error: str) -> str:
        raw = str(decode_error).strip().lower()
        if not raw:
            return ""
        if "control prefix" in raw:
            return "control_prefix"
        if "format parity mismatch" in raw:
            return "format"
        if "bootstrap rs decode failed" in raw:
            return "bootstrap_rs"
        if "bootstrap crc mismatch" in raw or "layered bootstrap crc mismatch" in raw:
            return "bootstrap_crc"
        if "payload rs decode failed" in raw:
            return "body_rs"
        if "payload crc mismatch" in raw or "layered body crc mismatch" in raw:
            return "body_crc"
        return ""

    def _accumulate_layered_format_trace(trace: Mapping[str, object], *, is_failure: bool) -> None:
        nonlocal layered_format_attempt_count
        nonlocal layered_format_fallback_attempts
        nonlocal layered_format_fallback_successes
        nonlocal layered_format_primary_threshold_sum
        nonlocal layered_format_primary_threshold_count
        nonlocal layered_format_fallback_threshold_sum
        nonlocal layered_format_fallback_threshold_count
        nonlocal layered_format_vote_margin_sum
        nonlocal layered_format_vote_margin_count
        nonlocal layered_format_vote_margin_min
        nonlocal layered_format_line_fail_horizontal
        nonlocal layered_format_line_fail_vertical

        layered_format_attempt_count += int(trace.get("format_attempt_count", 0) or 0)
        layered_format_fallback_attempts += int(trace.get("format_fallback_attempts", 0) or 0)
        layered_format_fallback_successes += int(trace.get("format_fallback_successes", 0) or 0)
        if "format_primary_threshold" in trace:
            layered_format_primary_threshold_sum += float(trace.get("format_primary_threshold", 0) or 0.0)
            layered_format_primary_threshold_count += 1
        fallback_threshold = int(trace.get("format_fallback_threshold", -1) or -1)
        if fallback_threshold >= 0:
            layered_format_fallback_threshold_sum += float(fallback_threshold)
            layered_format_fallback_threshold_count += 1
        vote_margin_min = float(trace.get("format_vote_margin_min", 0.0) or 0.0)
        vote_margin_avg = float(trace.get("format_vote_margin_avg", 0.0) or 0.0)
        if layered_format_vote_margin_count <= 0:
            layered_format_vote_margin_min = vote_margin_min
        else:
            layered_format_vote_margin_min = min(layered_format_vote_margin_min, vote_margin_min)
        layered_format_vote_margin_sum += vote_margin_avg
        layered_format_vote_margin_count += 1
        if not is_failure:
            return
        attempts = trace.get("attempts", [])
        latest = attempts[-1] if isinstance(attempts, list) and attempts else {}
        if not isinstance(latest, dict):
            return
        guessed_fields = latest.get("guessed_fields", {})
        mask_key = "unknown"
        if isinstance(guessed_fields, dict) and bool(guessed_fields.get("plausible", False)):
            mask_key = str(int(guessed_fields.get("mask_id", -1)))
        layered_format_mask_fail_counts[mask_key] = layered_format_mask_fail_counts.get(mask_key, 0) + 1
        disagree_positions = latest.get("disagree_bit_positions", [])
        if isinstance(disagree_positions, list):
            for pos in disagree_positions:
                idx = int(pos)
                if 0 <= idx < len(layered_format_bit_fail_counts):
                    layered_format_bit_fail_counts[idx] += 1
        layered_format_line_fail_horizontal += int(latest.get("horizontal_disagree_count", 0) or 0)
        layered_format_line_fail_vertical += int(latest.get("vertical_disagree_count", 0) or 0)
        if len(layered_format_fail_examples) < 8:
            layered_format_fail_examples.append(
                {
                    "mask_id_guess": -1 if mask_key == "unknown" else int(mask_key),
                    "repetition_level": int(latest.get("repetition_level", 0) or 0),
                    "threshold_mode": str(latest.get("threshold_mode", "")),
                    "threshold_value": latest.get("threshold_value"),
                    "vote_margin_min": float(latest.get("vote_margin_min", 0.0) or 0.0),
                    "vote_margin_avg": float(latest.get("vote_margin_avg", 0.0) or 0.0),
                    "horizontal_disagree_count": int(latest.get("horizontal_disagree_count", 0) or 0),
                    "vertical_disagree_count": int(latest.get("vertical_disagree_count", 0) or 0),
                    "disagree_bit_positions": list(latest.get("disagree_bit_positions", []) or []),
                    "raw_bytes_hex": str(latest.get("raw_bytes_hex", "")),
                }
            )

    def _accumulate_layered_control_trace(trace: Mapping[str, object], *, is_failure: bool) -> None:
        nonlocal layered_format_attempt_count
        nonlocal layered_format_primary_threshold_sum
        nonlocal layered_format_primary_threshold_count
        nonlocal layered_format_vote_margin_sum
        nonlocal layered_format_vote_margin_count
        nonlocal layered_format_vote_margin_min

        layered_format_attempt_count += int(trace.get("control_prefix_attempt_count", 0) or 0)
        if "control_prefix_threshold" in trace:
            layered_format_primary_threshold_sum += float(
                trace.get("control_prefix_threshold", 0) or 0.0
            )
            layered_format_primary_threshold_count += 1
        vote_margin_min = float(trace.get("control_prefix_vote_margin_min", 0.0) or 0.0)
        vote_margin_avg = float(trace.get("control_prefix_vote_margin_avg", 0.0) or 0.0)
        if layered_format_vote_margin_count <= 0:
            layered_format_vote_margin_min = vote_margin_min
        else:
            layered_format_vote_margin_min = min(layered_format_vote_margin_min, vote_margin_min)
        layered_format_vote_margin_sum += vote_margin_avg
        layered_format_vote_margin_count += 1
        if not is_failure:
            return
        attempts = trace.get("attempts", [])
        latest = attempts[-1] if isinstance(attempts, list) and attempts else {}
        if not isinstance(latest, dict):
            return
        disagree_positions = latest.get("disagree_bit_positions", [])
        if isinstance(disagree_positions, list):
            for pos in disagree_positions:
                idx = int(pos)
                if 0 <= idx < len(layered_format_bit_fail_counts):
                    layered_format_bit_fail_counts[idx] += 1
        if len(layered_format_fail_examples) < 8:
            layered_format_fail_examples.append(
                {
                    "mask_id_guess": int(latest.get("mask_id_guess", -1) or -1),
                    "threshold_mode": str(latest.get("threshold_mode", "")),
                    "threshold_value": latest.get("threshold_value"),
                    "vote_margin_min": float(latest.get("vote_margin_min", 0.0) or 0.0),
                    "vote_margin_avg": float(latest.get("vote_margin_avg", 0.0) or 0.0),
                    "disagree_bit_positions": list(latest.get("disagree_bit_positions", []) or []),
                    "raw_bytes_hex": str(latest.get("raw_bytes_hex", "")),
                    "decode_stage": str(latest.get("decode_stage", "")),
                }
            )

    def _attach_control_plane_state(report: Dict[str, object]) -> None:
        report["control_plane_kinds"] = sorted(list(assembler.control_items.keys()))
        if assembler.session_info is not None:
            report["control_session"] = dict(assembler.session_info)
        if assembler.layout_info is not None:
            report["control_layout"] = dict(assembler.layout_info)
        if assembler.generation_info is not None:
            report["control_generation"] = dict(assembler.generation_info)
        if assembler.generations:
            report["control_generations_seen"] = sorted(int(k) for k in assembler.generations.keys())

    def _attach_missing_chunks_state(report: Dict[str, object]) -> None:
        missing_count = assembler.missing_count()
        if missing_count is None:
            return
        report["missing_chunks"] = int(missing_count)
        report["missing_chunk_ids"] = list(assembler.missing_chunk_ids())

    def _debug_control_plane_state() -> Dict[str, object]:
        state: Dict[str, object] = {
            "control_plane_kinds": sorted(list(assembler.control_items.keys())),
            "control_session": None if assembler.session_info is None else dict(assembler.session_info),
            "control_layout": None if assembler.layout_info is None else dict(assembler.layout_info),
            "control_generation": (
                None if assembler.generation_info is None else dict(assembler.generation_info)
            ),
            "control_generations_seen": sorted(int(k) for k in assembler.generations.keys()),
        }
        return state

    def _attach_startup_state(report: Dict[str, object]) -> None:
        report["time_to_first_valid_frame_s"] = (
            0.0 if first_valid_frame_ts is None else max(0.0, first_valid_frame_ts - start)
        )
        report["time_to_first_data_frame_s"] = (
            0.0 if first_data_frame_ts is None else max(0.0, first_data_frame_ts - start)
        )
        report["time_to_first_new_chunk_s"] = (
            0.0 if first_new_chunk_ts is None else max(0.0, first_new_chunk_ts - start)
        )
        report["startup_sync_frames_decoded"] = float(startup_sync_frames_decoded)
        report["startup_control_frames_decoded"] = float(startup_control_frames_decoded)
        report["decoded_new_chunks"] = float(decoded_new_chunks)
        report["decoded_duplicate_chunks"] = float(decoded_duplicate_chunks)
        report["lock_decode_mode_counts"] = {
            "geometry_reuse": int(lock_decode_mode_geometry_reuse),
            "reacquire_locator": int(lock_decode_mode_reacquire_locator),
        }
        report["geometry_reuse_success_count"] = float(geometry_reuse_success_count)
        report["geometry_reuse_fail_count"] = float(geometry_reuse_fail_count)
        report["reacquire_attempt_count"] = float(reacquire_attempt_count)
        report["reacquire_success_count"] = float(reacquire_success_count)
        report["reacquire_fail_count"] = float(reacquire_fail_count)
        report["locked_geometry_age_max"] = float(locked_geometry_age_max)
        report["homography_rmse_reused_last"] = float(homography_rmse_reused_last)
        report["homography_rmse_reacquired_last"] = float(homography_rmse_reacquired_last)

    # ── Pipeline mode: screen source + basic protocol ──────────────────────────
    needs_runtime_roi_selection = roi_policy.needs_runtime_selection(
        source=config.source,
        forced_roi=forced_roi,
    )
    use_pipeline = _should_use_pipeline(
        source=config.source,
        protocol=config.protocol,
        debug_dir=config.debug_dir,
        needs_runtime_roi_selection=needs_runtime_roi_selection,
    )
    if config.debug_dir and config.source == "screen":
        print(
            "debug-dir set: forcing legacy loop (pipeline disabled) to emit debug snapshots"
        )
    if needs_runtime_roi_selection:
        print("select-region with auto_then_manual requires legacy loop for runtime ROI selection")
    if use_pipeline:
        # Prepare runtime configuration
        num_workers = config.decode_workers if config.decode_workers > 0 else None
        decode_workers = 1 if num_workers is None else num_workers
        grid_w, grid_h = _parse_module_grid(config.module_grid)
        guard_band, corner_size = _protocol_geometry(config.protocol)
        pipeline_seed_roi_local = _build_pipeline_seed_roi_local(source, forced_roi)

        # Infer manual mode from ROI presence
        manual_mode = forced_roi is not None

        pipeline = ScreenLiveRuntime(
            capture=source,
            assembler=assembler,
            decode_workers=decode_workers,
            prep_process=config.prep_process,
            capture_fps=config.capture_fps,
            capture_dump_dir=config.capture_dump_dir,
            capture_dump_max_frames=config.capture_dump_max_frames,
            protocol=config.protocol,
            grid_w=grid_w,
            grid_h=grid_h,
            guard_band=guard_band,
            corner_size=corner_size,
            manual_mode=manual_mode,
            initial_search_roi=pipeline_seed_roi_local,
        )
        print(
            "screen live runtime: protocol={0} workers={1} prep={2} capture_fps={3} seed_roi={4} mode={5}".format(
                config.protocol,
                decode_workers,
                config.prep_process,
                config.capture_fps,
                "none"
                if pipeline_seed_roi_local is None
                else "{0},{1},{2},{3}".format(*pipeline_seed_roi_local),
                "manual" if manual_mode else "auto",
            )
        )
        pipeline.start()
        try:
            deadline = (start + config.max_seconds) if config.max_seconds > 0 else None
            last_assembled = 0
            last_assembled_ts = start
            last_rate_ts = start
            last_rate_assembled_bytes = 0
            last_fps_ts = start
            last_fps_captured = 0
            last_fps_decoded = 0
            last_capture_timing = {
                "capture_grab_time_ms": 0.0,
                "capture_copy_time_ms": 0.0,
                "capture_dedup_time_ms": 0.0,
                "capture_grab_ops": 0,
                "capture_copy_ops": 0,
                "capture_dedup_ops": 0,
                "ipc_recv_time_ms": 0.0,
                "ipc_recv_ops": 0,
                "fingerprint_time_ms": 0.0,
                "fingerprint_ops": 0,
                "materialize_time_ms": 0.0,
                "materialize_ops": 0,
                "dump_time_ms": 0.0,
                "dump_ops": 0,
            }
            while True:
                pipeline.check_errors()
                now = time.time()
                if deadline is not None and now > deadline:
                    snap = pipeline.stats.snapshot()
                    _sync_transfer_stats_from_pipeline(snap)
                    final_report = cast(
                        Dict[str, object], dict(stats.finalize(output_size_bytes=0, ts=now))
                    )
                    _attach_pipeline_metrics(final_report, snap)
                    _attach_control_plane_state(final_report)
                    _attach_missing_chunks_state(final_report)
                    _attach_gray4_state(
                        final_report,
                        failure_error=str(snap.get("last_decode_error", "") or ""),
                        failure_class=str(snap.get("last_failure_class", "") or ""),
                        success_meta=last_v31_meta,
                        failure_counts={
                            "header": snap.get("failure_count_header", 0),
                            "payload": snap.get("failure_count_payload", 0),
                            "locator": snap.get("failure_count_locator", 0),
                            "unknown": snap.get("failure_count_unknown", 0),
                        },
                    )
                    final_report["status"] = "timeout_max_seconds"
                    _write_report(config.report_json, final_report)
                    print("receiver timeout: max-seconds reached")
                    return 2

                snap = pipeline.stats.snapshot()
                assembled = snap["assembled"]

                # Check if assembly is complete
                if assembler.complete():
                    # Assembly complete - stop pipeline immediately
                    pipeline.stop()
                    break

                if assembled > last_assembled:
                    last_assembled = assembled
                    last_assembled_ts = now
                elif now - last_assembled_ts > config.max_idle_seconds and assembled > 0:
                    _sync_transfer_stats_from_pipeline(snap)
                    final_report = cast(
                        Dict[str, object], dict(stats.finalize(output_size_bytes=0, ts=now))
                    )
                    _attach_pipeline_metrics(final_report, snap)
                    _attach_control_plane_state(final_report)
                    _attach_missing_chunks_state(final_report)
                    _attach_gray4_state(
                        final_report,
                        failure_error=str(snap.get("last_decode_error", "") or ""),
                        failure_class=str(snap.get("last_failure_class", "") or ""),
                        success_meta=last_v31_meta,
                        failure_counts={
                            "header": snap.get("failure_count_header", 0),
                            "payload": snap.get("failure_count_payload", 0),
                            "locator": snap.get("failure_count_locator", 0),
                            "unknown": snap.get("failure_count_unknown", 0),
                        },
                    )
                    final_report["status"] = "timeout_idle"
                    _write_report(config.report_json, final_report)
                    print("receiver timeout: no new chunks for {0}s".format(config.max_idle_seconds))
                    return 2
                elif assembled == 0 and now - start > config.max_idle_seconds:
                    _sync_transfer_stats_from_pipeline(snap)
                    final_report = cast(
                        Dict[str, object], dict(stats.finalize(output_size_bytes=0, ts=now))
                    )
                    _attach_pipeline_metrics(final_report, snap)
                    _attach_control_plane_state(final_report)
                    _attach_missing_chunks_state(final_report)
                    _attach_gray4_state(
                        final_report,
                        failure_error=str(snap.get("last_decode_error", "") or ""),
                        failure_class=str(snap.get("last_failure_class", "") or ""),
                        success_meta=last_v31_meta,
                        failure_counts={
                            "header": snap.get("failure_count_header", 0),
                            "payload": snap.get("failure_count_payload", 0),
                            "locator": snap.get("failure_count_locator", 0),
                            "unknown": snap.get("failure_count_unknown", 0),
                        },
                    )
                    final_report["status"] = "timeout_idle"
                    _write_report(config.report_json, final_report)
                    print(
                        "receiver timeout: no valid frames for {0}s".format(config.max_idle_seconds)
                    )
                    return 2

                if now >= next_stats_ts:
                    missing = assembler.missing_count()
                    elapsed_for_rate = max(1e-6, now - last_rate_ts)
                    assembled_bytes_now = int(snap.get("assembled_bytes", 0))
                    delta_assembled_bytes = max(0, assembled_bytes_now - last_rate_assembled_bytes)
                    rx_kBps = (float(delta_assembled_bytes) / 1000.0) / elapsed_for_rate
                    elapsed_for_fps = max(1e-6, now - last_fps_ts)
                    captured_now = int(snap.get("captured", 0))
                    decoded_now = int(snap.get("decode_ok", 0))
                    cap_fps = float(max(0, captured_now - last_fps_captured)) / elapsed_for_fps
                    dec_fps = float(max(0, decoded_now - last_fps_decoded)) / elapsed_for_fps
                    raw_grab_fps = float(snap.get("raw_grab_fps", 0.0))
                    prep_fps = float(snap.get("prep_fps", 0.0))
                    accepted_fps = float(snap.get("accepted_for_decode_fps", 0.0))
                    prep_backlog = int(snap.get("prep_backlog_frames", 0))
                    overwrite_count = int(snap.get("capture_overwrite_count", 0))
                    decode_queue_depth = int(snap.get("decode_queue_depth", 0))
                    grab_ops_now = int(snap.get("capture_grab_ops", 0))
                    copy_ops_now = int(snap.get("capture_copy_ops", 0))
                    dedup_ops_now = int(snap.get("capture_dedup_ops", 0))
                    grab_ops_delta = max(
                        0, grab_ops_now - int(last_capture_timing["capture_grab_ops"])
                    )
                    copy_ops_delta = max(
                        0, copy_ops_now - int(last_capture_timing["capture_copy_ops"])
                    )
                    dedup_ops_delta = max(
                        0, dedup_ops_now - int(last_capture_timing["capture_dedup_ops"])
                    )
                    grab_ms = max(
                        0.0,
                        float(snap.get("capture_grab_time_ms", 0.0))
                        - float(last_capture_timing["capture_grab_time_ms"]),
                    ) / float(max(1, grab_ops_delta))
                    copy_ms = max(
                        0.0,
                        float(snap.get("capture_copy_time_ms", 0.0))
                        - float(last_capture_timing["capture_copy_time_ms"]),
                    ) / float(max(1, copy_ops_delta))
                    ipc_ops_now = int(snap.get("ipc_recv_ops", 0))
                    ipc_ops_delta = max(0, ipc_ops_now - int(last_capture_timing["ipc_recv_ops"]))
                    ipc_recv_ms = max(
                        0.0,
                        float(snap.get("ipc_recv_time_ms", 0.0))
                        - float(last_capture_timing["ipc_recv_time_ms"]),
                    ) / float(max(1, ipc_ops_delta))
                    dedup_ms = max(
                        0.0,
                        float(snap.get("capture_dedup_time_ms", 0.0))
                        - float(last_capture_timing["capture_dedup_time_ms"]),
                    ) / float(max(1, dedup_ops_delta))
                    fp_ops_now = int(snap.get("fingerprint_ops", 0))
                    fp_ops_delta = max(0, fp_ops_now - int(last_capture_timing["fingerprint_ops"]))
                    fp_ms = max(
                        0.0,
                        float(snap.get("fingerprint_time_ms", 0.0))
                        - float(last_capture_timing["fingerprint_time_ms"]),
                    ) / float(max(1, fp_ops_delta))
                    mat_ops_now = int(snap.get("materialize_ops", 0))
                    mat_ops_delta = max(0, mat_ops_now - int(last_capture_timing["materialize_ops"]))
                    mat_ms = max(
                        0.0,
                        float(snap.get("materialize_time_ms", 0.0))
                        - float(last_capture_timing["materialize_time_ms"]),
                    ) / float(max(1, mat_ops_delta))
                    dump_ops_now = int(snap.get("dump_ops", 0))
                    dump_ops_delta = max(0, dump_ops_now - int(last_capture_timing["dump_ops"]))
                    dump_ms = max(
                        0.0,
                        float(snap.get("dump_time_ms", 0.0))
                        - float(last_capture_timing["dump_time_ms"]),
                    ) / float(max(1, dump_ops_delta))
                    print(
                        "captured={0} decoded={1} assembled={2} missing={3} dropped={4} dedup={5} cap_fps={6:.2f} raw_grab_fps={7:.2f} prep_fps={8:.2f} accepted_fps={9:.2f} dec_fps={10:.2f} prep_backlog={11} overwrite={12} decode_q={13} rx_KBps={14:.2f} grab_ms={15:.2f} copy_ms={16:.2f} ipc_recv_ms={17:.2f} dedup_ms={18:.2f} fp_ms={19:.2f} mat_ms={20:.2f} dump_ms={21:.2f}".format(
                            snap["captured"],
                            snap["decode_ok"],
                            snap["assembled"],
                            "?" if missing is None else missing,
                            "{0}/{1}".format(
                                snap["dropped_queue_full"], snap["dropped_result_queue_full"]
                            ),
                            snap["duplicate_frames"],
                            cap_fps,
                            raw_grab_fps,
                            prep_fps,
                            accepted_fps,
                            dec_fps,
                            prep_backlog,
                            overwrite_count,
                            decode_queue_depth,
                            rx_kBps,
                            grab_ms,
                            copy_ms,
                            ipc_recv_ms,
                            dedup_ms,
                            fp_ms,
                            mat_ms,
                            dump_ms,
                        )
                    )
                    last_rate_ts = now
                    last_rate_assembled_bytes = assembled_bytes_now
                    last_fps_ts = now
                    last_fps_captured = captured_now
                    last_fps_decoded = decoded_now
                    last_capture_timing = {
                        "capture_grab_time_ms": float(snap.get("capture_grab_time_ms", 0.0)),
                        "capture_copy_time_ms": float(snap.get("capture_copy_time_ms", 0.0)),
                        "capture_dedup_time_ms": float(snap.get("capture_dedup_time_ms", 0.0)),
                        "capture_grab_ops": grab_ops_now,
                        "capture_copy_ops": copy_ops_now,
                        "capture_dedup_ops": dedup_ops_now,
                        "ipc_recv_time_ms": float(snap.get("ipc_recv_time_ms", 0.0)),
                        "ipc_recv_ops": ipc_ops_now,
                        "fingerprint_time_ms": float(snap.get("fingerprint_time_ms", 0.0)),
                        "fingerprint_ops": fp_ops_now,
                        "materialize_time_ms": float(snap.get("materialize_time_ms", 0.0)),
                        "materialize_ops": mat_ops_now,
                        "dump_time_ms": float(snap.get("dump_time_ms", 0.0)),
                        "dump_ops": dump_ops_now,
                    }
                    next_stats_ts = now + max(0.1, config.stats_interval)

                if pipeline.done_event.wait(timeout=0.2):
                    break

            pipeline.check_errors()
            payload_bytes = assembler.payload()
            if assembler.manifest is None:
                raise RuntimeError("manifest not received")
            output_path = restore_payload(payload_bytes, assembler.manifest, config.output_dir)
            now = time.time()
            snap = pipeline.stats.snapshot()
            _sync_transfer_stats_from_pipeline(snap)
            stats.payload_bytes = len(payload_bytes)
            final_report = cast(
                Dict[str, object],
                dict(stats.finalize(output_size_bytes=len(payload_bytes), ts=now)),
            )
            _attach_pipeline_metrics(final_report, snap)
            _attach_control_plane_state(final_report)
            _attach_missing_chunks_state(final_report)
            _attach_gray4_state(
                final_report,
                failure_error=str(snap.get("last_decode_error", "") or ""),
                failure_class=str(snap.get("last_failure_class", "") or ""),
                success_meta=last_v31_meta,
                failure_counts={
                    "header": snap.get("failure_count_header", 0),
                    "payload": snap.get("failure_count_payload", 0),
                    "locator": snap.get("failure_count_locator", 0),
                    "unknown": snap.get("failure_count_unknown", 0),
                },
            )
            final_report["status"] = "ok"
            final_report["output_path"] = output_path
            _write_report(config.report_json, final_report)
            print("restore complete: {0}".format(output_path))
            print(
                "summary captured={0} decoded={1} assembled={2} dropped={3}/{4}".format(
                    snap["captured"],
                    snap["decode_ok"],
                    snap["assembled"],
                    snap["dropped_queue_full"],
                    snap["dropped_result_queue_full"],
                )
            )
            return 0
        except KeyboardInterrupt:
            print("\nreceiver interrupted: stopping pipeline and cleaning up...")
            pipeline.stop()
        finally:
            pipeline.join(timeout=3.0)
            runtime_error = None
            try:
                pipeline.check_errors()
            except RuntimeError as exc:
                runtime_error = exc
            if final_report is None:
                snap = pipeline.stats.snapshot()
                _sync_transfer_stats_from_pipeline(snap)
                report = cast(
                    Dict[str, object], dict(stats.finalize(output_size_bytes=0, ts=time.time()))
                )
                _attach_pipeline_metrics(report, snap)
                _attach_control_plane_state(report)
                _attach_gray4_state(
                    report,
                    failure_error=str(snap.get("last_decode_error", "") or ""),
                    failure_class=str(snap.get("last_failure_class", "") or ""),
                    success_meta=last_v31_meta,
                    failure_counts={
                        "header": snap.get("failure_count_header", 0),
                        "payload": snap.get("failure_count_payload", 0),
                        "locator": snap.get("failure_count_locator", 0),
                        "unknown": snap.get("failure_count_unknown", 0),
                    },
                )
                report["status"] = "aborted"
                if runtime_error is not None:
                    report["error"] = str(runtime_error)
                _write_report(config.report_json, report)
        return 1
    # ── Legacy single-thread mode ────────────────────────────────────────────

    try:
        for frame in source.iter_frames():
            now = time.time()
            frame_index += 1
            frame_v31_meta = None
            capture_region = getattr(source, "active_region", None)
            roi_mgr = RoiManager(capture_region)
            forced_roi_local = roi_mgr.abs_to_local(forced_roi, frame.shape)
            manual_mode_now = roi_policy.manual_active(stats)
            manual_decode_roi_local = (
                roi_mgr.expand(forced_roi_local, frame.shape, roi_policy.pad_px)
                if manual_mode_now
                else forced_roi_local
            )
            if (
                (not replay_mode)
                and config.detect_mode != "full"
                and v3_track_roi is None
                and manual_decode_roi_local is not None
            ):
                v3_track_roi = manual_decode_roi_local

            if config.max_seconds > 0 and now - start > config.max_seconds:
                final_report = cast(
                    Dict[str, object], dict(stats.finalize(output_size_bytes=0, ts=now))
                )
                final_report["status"] = "timeout_max_seconds"
                _attach_v3_metrics(final_report)
                _attach_missing_chunks_state(final_report)
                _attach_protocol_debug(final_report)
                _write_report(config.report_json, final_report)
                print("receiver timeout: max-seconds reached")
                return 2

            if now - last_good > config.max_idle_seconds:
                final_report = cast(
                    Dict[str, object], dict(stats.finalize(output_size_bytes=0, ts=now))
                )
                final_report["status"] = "timeout_idle"
                _attach_v3_metrics(final_report)
                _attach_missing_chunks_state(final_report)
                _attach_protocol_debug(final_report)
                _write_report(config.report_json, final_report)
                print("receiver timeout: no valid frames for {0}s".format(config.max_idle_seconds))
                return 2

            if threshold is None:
                # Auto threshold - use simple default for basic protocol
                threshold = 128
                print("using default threshold={0}".format(threshold))

            # manual mode selector on first frame if no roi yet.
            if roi_policy.mode == "manual" and forced_roi is None and roi_policy.interactive:
                stats.mark_manual_select_attempt()
                selected = select_region(get_monitor_region(config.monitor_index))
                if selected is None:
                    raise RuntimeError("manual roi selection canceled")
                forced_roi = ensure_roi_valid(selected)
                forced_roi_local = roi_mgr.abs_to_local(forced_roi, frame.shape)
                manual_decode_roi_local = roi_mgr.expand(
                    forced_roi_local, frame.shape, roi_policy.pad_px
                )
                v3_track_roi = manual_decode_roi_local
                stats.mark_manual_roi(switched=False)
                if config.roi_profile:
                    save_profile(config.roi_profile, forced_roi, config.monitor_index)

            try:
                t_decode0 = time.perf_counter()
                if config.protocol in ("basic", "compact", "gray4", "layered"):
                    layered_failure_trace = None
                    last_grid_exc = None
                    if replay_mode:
                        v31_mode = "full"
                    else:
                        v31_mode = (
                            "track"
                            if v3_track_roi is not None
                            else ("full" if v3_mode == "full" else "track")
                        )
                    manual_strict = manual_decode_roi_local is not None and roi_policy.manual_active(
                        stats
                    )
                    roi_only = manual_strict
                    decode_fn = (
                        decode_frame_layered if config.protocol == "layered" else
                        decode_frame_gray4 if config.protocol == "gray4" else
                        decode_frame_compact if config.protocol == "compact" else decode_frame_basic
                    )
                    guard_band, corner_size = _protocol_geometry(config.protocol)
                    for gw, gh in grid_candidates:
                        decode_attempt_total += 1
                        try:
                            if config.protocol == "layered" and layered_locked_geometry is not None:
                                lock_decode_mode_geometry_reuse += 1
                                header, payload, meta31 = decode_frame_layered_with_geometry(
                                    frame=frame,
                                    geometry=layered_locked_geometry,
                                    grid_w=gw,
                                    grid_h=gh,
                                    guard_band=guard_band,
                                    corner_size=corner_size,
                                )
                                geometry_reuse_success_count += 1
                                layered_locked_geometry_age += 1
                                if layered_locked_geometry_age > locked_geometry_age_max:
                                    locked_geometry_age_max = layered_locked_geometry_age
                                homography_rmse_reused_last = float(
                                    getattr(meta31, "homography_rmse", 0.0) or 0.0
                                )
                            else:
                                lock_decode_mode_reacquire_locator += 1
                                reacquire_attempt_count += 1
                                header, payload, meta31 = decode_fn(
                                    frame=frame,
                                    detect_mode=v31_mode,
                                    forced_roi=manual_decode_roi_local
                                    if manual_strict
                                    else v3_track_roi,
                                    grid_w=gw,
                                    grid_h=gh,
                                    guard_band=guard_band,
                                    corner_size=corner_size,
                                    roi_only=roi_only,
                                    manual_strict=manual_strict,
                                    locator_engine=config.locator_engine,
                                    locator_confidence_threshold=config.locator_confidence_threshold,
                                )
                                reacquire_success_count += 1
                                homography_rmse_reacquired_last = float(
                                    getattr(meta31, "homography_rmse", 0.0) or 0.0
                                )
                                layered_locked_geometry_age = 0
                            decode_attempt_total += max(0, int(meta31.decode_attempts) - 1)
                            grid_w, grid_h = gw, gh
                            break
                        except Exception as grid_exc:  # noqa: PERF203
                            last_grid_exc = grid_exc
                            if config.protocol == "layered" and layered_locked_geometry is not None:
                                geometry_reuse_fail_count += 1
                                layered_locked_fail_streak += 1
                                if layered_locked_fail_streak >= layered_locked_fail_reacquire_threshold:
                                    layered_locked_geometry = None
                                    layered_locked_fail_streak = 0
                                    layered_locked_geometry_age = 0
                                continue
                            if config.protocol == "layered":
                                reacquire_fail_count += 1
                            # Per-frame recovery: if track path fails, retry the same frame in full mode.
                            if not replay_mode and not manual_strict and v31_mode == "track":
                                try:
                                    decode_attempt_total += 1
                                    header, payload, meta31 = decode_fn(
                                        frame=frame,
                                        detect_mode="full",
                                        forced_roi=forced_roi_local,
                                        grid_w=gw,
                                        grid_h=gh,
                                        guard_band=guard_band,
                                        corner_size=corner_size,
                                        roi_only=False,
                                        manual_strict=False,
                                        locator_engine=config.locator_engine,
                                        locator_confidence_threshold=config.locator_confidence_threshold,
                                    )
                                    decode_attempt_total += max(0, int(meta31.decode_attempts) - 1)
                                    grid_w, grid_h = gw, gh
                                    break
                                except Exception as full_exc:  # noqa: PERF203
                                    last_grid_exc = full_exc
                    else:
                        raise cast(Exception, last_grid_exc)
                    stats.on_locator(confidence=float(meta31.det_confidence), failed=False)
                    frame_v31_meta = meta31
                    last_v31_meta = meta31
                    protocol_report_adapter.accumulate_success(meta31)
                    if config.protocol == "layered":
                        trace = getattr(meta31, "control_trace", None)
                        if isinstance(trace, dict):
                            _accumulate_layered_control_trace(trace, is_failure=False)
                    protocol_path_used = config.protocol
                    last_det_bbox = meta31.det_bbox
                    last_det_confidence = float(meta31.det_confidence)
                    locator_new_fail_reason = meta31.new_fail_reason
                    locator_new_elapsed_ms = float(meta31.new_elapsed_ms)
                    locator_legacy_used = bool(meta31.legacy_used)
                    locator_legacy_elapsed_ms = float(meta31.legacy_elapsed_ms)
                    v3_fail_streak = 0
                    if config.protocol == "layered":
                        geometry = LayeredProtocolDecoder.geometry_from_meta(meta31)
                        if geometry is not None:
                            layered_locked_geometry = geometry
                        layered_locked_fail_streak = 0
                    bx, by, bw, bh = meta31.det_bbox
                    if prev_bbox is not None:
                        px, py, pw, ph = prev_bbox
                        dx = abs(bx - px) + abs(by - py) + abs(bw - pw) + abs(bh - ph)
                        bbox_jitter_sum += float(dx)
                        bbox_jitter_count += 1
                    prev_bbox = (bx, by, bw, bh)
                    if not replay_mode:
                        if manual_strict and manual_decode_roi_local is not None:
                            v3_track_roi = manual_decode_roi_local
                        else:
                            v3_track_roi = roi_mgr.build_track_roi(
                                (bx, by, bw, bh),
                                frame.shape,
                                config.track_margin_px,
                            )
                    if config.detect_mode != "full" and not replay_mode:
                        v3_mode = "track"
                else:
                    raise ValueError(
                        f"Protocol '{config.protocol}' not supported, use 'basic', 'compact', 'gray4', or 'layered'"
                    )
                auto_fail_count = 0
                last_decode_error = None
                if config.protocol in ("gray4", "layered"):
                    last_gray4_failure_error = None
                    last_gray4_failure_class = ""
                if first_valid_frame_ts is None:
                    first_valid_frame_ts = now
                decode_time_sum += max(0.0, time.perf_counter() - t_decode0)
                decode_time_count += 1
            except Exception as exc:
                decode_time_sum += max(0.0, time.perf_counter() - t_decode0)
                decode_time_count += 1
                decoded = False
                last_exc = exc
                manual_strict = manual_decode_roi_local is not None and roi_policy.manual_active(
                    stats
                )
                if (
                    not decoded
                    and False  # Legacy protocol block size auto-selection removed
                    and selected_block_size is None
                    and len(block_size_candidates) > 1
                ):
                    # This branch is now unreachable - kept for structure
                    pass
                if decoded:
                    auto_fail_count = 0
                    last_decode_error = None
                    pass
                else:
                    last_decode_error = str(last_exc)
                    if config.protocol in ("gray4", "layered"):
                        last_gray4_failure_error = last_decode_error
                        last_gray4_failure_class = _classify_gray4_decode_failure(last_decode_error)
                        protocol_report_adapter.accumulate_failure(
                            last_decode_error,
                            failure_class=last_gray4_failure_class,
                            trace=getattr(last_exc, "trace", None),
                        )
                        if last_gray4_failure_class in gray4_failure_counts:
                            gray4_failure_counts[last_gray4_failure_class] += 1
                        elif last_gray4_failure_class:
                            gray4_failure_counts["unknown"] += 1
                        if config.protocol == "layered":
                            layered_detail = _classify_layered_decode_failure_detail(last_decode_error)
                            if layered_detail in layered_failure_counts:
                                layered_failure_counts[layered_detail] += 1
                            trace = getattr(last_exc, "trace", None)
                            if isinstance(trace, dict):
                                layered_failure_trace = dict(trace)
                                _accumulate_layered_control_trace(
                                    trace, is_failure=(layered_detail == "control_prefix")
                                )
                    if config.protocol in ("basic", "compact"):
                        v3_fail_streak += 1
                        # Fast recovery: return to full search after a few consecutive misses.
                        if v3_fail_streak >= 3 and not replay_mode:
                            v3_mode = "full"
                            v3_track_roi = forced_roi_local
                    stats.on_frame(decoded_ok=False, payload_len=0, ts=now)
                    if "locator" in str(last_exc).lower():
                        stats.on_locator(confidence=0.0, failed=True)
                        auto_fail_count += 1
                    if (
                        roi_policy.mode == "auto_then_manual"
                        and roi_policy.interactive
                        and forced_roi is None
                        and auto_fail_count >= roi_policy.auto_fail_threshold
                        and manual_attempts < roi_policy.manual_max_retries
                    ):
                        manual_attempts += 1
                        stats.mark_manual_select_attempt()
                        print(
                            "auto locator failed, switching to manual selection (attempt {0})".format(
                                manual_attempts
                            )
                        )
                        selected = select_region(get_monitor_region(config.monitor_index))
                        if selected is not None:
                            forced_roi = ensure_roi_valid(selected)
                            stats.mark_manual_roi(switched=True)
                            forced_roi_local = roi_mgr.abs_to_local(
                                forced_roi, frame.shape
                            )
                            manual_decode_roi_local = roi_mgr.expand(
                                forced_roi_local, frame.shape, roi_policy.pad_px
                            )
                            v3_track_roi = manual_decode_roi_local
                            auto_fail_count = 0
                            if config.roi_profile:
                                save_profile(config.roi_profile, forced_roi, config.monitor_index)
                    if now >= next_stats_ts:
                        _print_stats(stats.snapshot(ts=now), assembler.missing_count())
                        next_stats_ts = now + max(0.1, config.stats_interval)
                    if debug_manager:
                        debug_manager.maybe_dump(
                            now=now,
                            threshold=threshold,
                            dump_kwargs={
                                "frame_index": frame_index,
                                "frame": frame,
                                "forced_roi_local": forced_roi_local,
                                "forced_roi_abs": forced_roi,
                                "capture_region": capture_region,
                                "decode_error": last_decode_error,
                                "protocol_path_used": protocol_path_used,
                                "track_roi_local": v3_track_roi,
                                "det_bbox_local": last_det_bbox,
                                "manual_strict": roi_policy.manual_active(stats),
                                "v31_meta": frame_v31_meta,
                                "grid_w": grid_w,
                                "grid_h": grid_h,
                                "locator_confidence_threshold": config.locator_confidence_threshold,
                                "layered_failure_trace": layered_failure_trace,
                                "protocol": config.protocol,
                                **_debug_control_plane_state(),
                            },
                        )
                    continue

            if debug_manager:
                debug_manager.maybe_dump(
                    now=now,
                    threshold=threshold,
                    dump_kwargs={
                        "frame_index": frame_index,
                        "frame": frame,
                        "forced_roi_local": forced_roi_local,
                        "forced_roi_abs": forced_roi,
                        "capture_region": capture_region,
                        "decode_error": last_decode_error,
                        "protocol_path_used": protocol_path_used,
                        "track_roi_local": v3_track_roi,
                        "det_bbox_local": last_det_bbox,
                        "manual_strict": roi_policy.manual_active(stats),
                        "v31_meta": frame_v31_meta,
                        "grid_w": grid_w,
                        "grid_h": grid_h,
                        "locator_confidence_threshold": config.locator_confidence_threshold,
                        "layered_failure_trace": None,
                        "protocol": config.protocol,
                        **_debug_control_plane_state(),
                        "decoded_chunk_id": int(header.chunk_id),
                        "decoded_payload": payload,
                    },
                )

            is_data_frame = int(header.frame_type) == int(FRAME_DATA)

            if not is_data_frame:
                if first_new_chunk_ts is None:
                    startup_sync_frames_decoded += 1
                stats.on_frame(decoded_ok=True, payload_len=0, ts=now)
                if now >= next_stats_ts:
                    _print_stats(stats.snapshot(ts=now), assembler.missing_count())
                    next_stats_ts = now + max(0.1, config.stats_interval)
                continue

            last_good = now
            if first_data_frame_ts is None:
                first_data_frame_ts = now
            stats.on_frame(decoded_ok=True, payload_len=len(payload), ts=now)
            control_kind = control_kind_from_wire_chunk_id(int(header.chunk_id))
            if control_kind is not None:
                if first_new_chunk_ts is None:
                    startup_control_frames_decoded += 1
                assembler.add_control(control_kind, payload)
            else:
                is_new_chunk = int(header.chunk_id) not in assembler.chunks
                assembler.add(header.chunk_id, payload)
                if is_new_chunk:
                    decoded_new_chunks += 1
                    if first_new_chunk_ts is None:
                        first_new_chunk_ts = now
                else:
                    decoded_duplicate_chunks += 1

            if now >= next_stats_ts:
                _print_stats(stats.snapshot(ts=now), assembler.missing_count())
                next_stats_ts = now + max(0.1, config.stats_interval)

            if assembler.complete():
                payload_bytes = assembler.payload()
                if assembler.manifest is None:
                    continue
                output_path = restore_payload(payload_bytes, assembler.manifest, config.output_dir)
                final_report = cast(
                    Dict[str, object],
                    dict(stats.finalize(output_size_bytes=len(payload_bytes), ts=time.time())),
                )
                final_report["status"] = "ok"
                final_report["output_path"] = output_path
                _attach_v3_metrics(final_report)
                _attach_gray4_state(
                    final_report,
                    failure_error=last_gray4_failure_error,
                    failure_class=last_gray4_failure_class,
                    success_meta=last_v31_meta,
                    failure_counts=gray4_failure_counts,
                )
                _attach_protocol_debug(final_report)
                if last_v3_meta is not None:
                    final_report["protocol_version_used"] = float(last_v3_meta.protocol_version_used)
                    final_report["det_confidence"] = float(last_v3_meta.det_confidence)
                    final_report["homography_rmse"] = float(last_v3_meta.homography_rmse)
                    final_report["rs_corrected_symbols"] = float(last_v3_meta.rs_corrected_symbols)
                    final_report["crc_ok"] = 1.0 if last_v3_meta.crc_ok else 0.0
                    final_report["mask_id"] = float(last_v3_meta.mask_id)
                    final_report["grid_size"] = last_v3_meta.grid_size
                if last_v31_meta is not None:
                    final_report["protocol_version_used"] = float(
                        last_v31_meta.protocol_version_used
                    )
                    final_report["det_confidence"] = float(last_v31_meta.det_confidence)
                    final_report["homography_rmse"] = float(last_v31_meta.homography_rmse)
                    final_report["rs_corrected_symbols"] = float(last_v31_meta.rs_corrected_symbols)
                    final_report["crc_ok"] = 1.0 if last_v31_meta.crc_ok else 0.0
                    final_report["mask_id"] = float(last_v31_meta.mask_id)
                    final_report["grid_size"] = last_v31_meta.grid_size
                    final_report["locator_engine"] = last_v31_meta.locator_engine
                    final_report["locator_fail_reason"] = last_v31_meta.fail_reason
                    final_report["locator_elapsed_ms"] = float(last_v31_meta.elapsed_ms)
                    final_report["gray4_total_decode_ms"] = float(
                        getattr(last_v31_meta, "total_decode_ms", 0.0)
                    )
                    final_report["gray4_phase_candidates_tried"] = float(
                        getattr(last_v31_meta, "phase_candidates_tried", 0)
                    )
                    final_report["gray4_phase_sweep_used"] = 1.0 if bool(
                        getattr(last_v31_meta, "phase_sweep_used", False)
                    ) else 0.0
                    final_report["gray4_avg_symbol_confidence"] = float(
                        getattr(last_v31_meta, "avg_symbol_confidence", 0.0)
                    )
                    final_report["legacy_used"] = 1.0 if last_v31_meta.legacy_used else 0.0
                    final_report["new_fail_reason"] = last_v31_meta.new_fail_reason
                    final_report["new_elapsed_ms"] = float(last_v31_meta.new_elapsed_ms)
                    final_report["legacy_elapsed_ms"] = float(last_v31_meta.legacy_elapsed_ms)
                else:
                    final_report["protocol_version_used"] = 3.1
                final_report["roi_mode_used"] = roi_policy.report_mode
                _attach_control_plane_state(final_report)
                _attach_missing_chunks_state(final_report)
                _attach_startup_state(final_report)
                if forced_roi is not None:
                    final_report["roi"] = {
                        "x": forced_roi[0],
                        "y": forced_roi[1],
                        "w": forced_roi[2],
                        "h": forced_roi[3],
                    }
                capture_region = getattr(source, "active_region", None)
                if capture_region is not None:
                    final_report["capture_region"] = {
                        "x": capture_region[0],
                        "y": capture_region[1],
                        "w": capture_region[2],
                        "h": capture_region[3],
                    }
                _write_report(config.report_json, final_report)
                print("restore complete: {0}".format(output_path))
                print(
                    "summary goodput_KiBps={0:.2f} end_to_end_KiBps={1:.2f} bad_frame_rate={2:.4f} recovery_latency_s={3:.3f}".format(
                        final_report["goodput_kibps"],
                        final_report["end_to_end_kibps"],
                        final_report["bad_frame_rate"],
                        final_report["recovery_latency_s"],
                    )
                )
                return 0

        final_report = cast(
            Dict[str, object], dict(stats.finalize(output_size_bytes=0, ts=time.time()))
        )
        final_report["status"] = "source_exhausted"
        _attach_v3_metrics(final_report)
        _attach_control_plane_state(final_report)
        _attach_missing_chunks_state(final_report)
        _attach_startup_state(final_report)
        _attach_gray4_state(
            final_report,
            failure_error=last_gray4_failure_error,
            failure_class=last_gray4_failure_class,
            success_meta=last_v31_meta,
            failure_counts=gray4_failure_counts,
        )
        _attach_protocol_debug(final_report)
        _write_report(config.report_json, final_report)
        print("receiver ended: source exhausted")
        return 1
    finally:
        if final_report is None:
            report = cast(
                Dict[str, object], dict(stats.finalize(output_size_bytes=0, ts=time.time()))
            )
            report["status"] = "aborted"
            _attach_v3_metrics(report)
            _attach_control_plane_state(report)
            _attach_startup_state(report)
            _attach_gray4_state(
                report,
                failure_error=last_gray4_failure_error,
                failure_class=last_gray4_failure_class,
                success_meta=last_v31_meta,
                failure_counts=gray4_failure_counts,
            )
            _attach_protocol_debug(report)
            _write_report(config.report_json, report)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
