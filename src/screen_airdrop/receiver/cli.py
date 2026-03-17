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


def _protocol_geometry(protocol: str) -> Tuple[int, int]:
    if protocol in ("compact", "gray4", "layered"):
        return (1, 7)
    return (2, 9)


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


def _build_source(args, region):
    if args.source == "replay":
        if not args.frames_dir:
            raise ValueError("--frames-dir is required when --source replay")
        return FrameReplaySource(frames_dir=args.frames_dir)

    capture_region = None
    # Manual ROI mode should crop at capture stage to avoid coordinate drift and
    # selector-overlay interference in subsequent decode frames.
    if args.roi_mode == "manual" and region is not None:
        capture_region = region

    return ScreenCapture(
        window_title=args.window_title,
        region=capture_region,
        monitor_index=args.monitor_index,
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


def _ensure_roi_valid(roi: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    x, y, w, h = roi
    if w < 128 or h < 128:
        raise ValueError("roi too small; minimum is 128x128")
    return int(x), int(y), int(w), int(h)


def _roi_abs_to_local(
    roi_abs: Optional[Tuple[int, int, int, int]],
    capture_region: Optional[Tuple[int, int, int, int]],
    frame_shape: Tuple[int, int, int],
) -> Optional[Tuple[int, int, int, int]]:
    if roi_abs is None:
        return None
    rx, ry, rw, rh = roi_abs
    if rw <= 0 or rh <= 0:
        return None
    if capture_region is None:
        return roi_abs
    cx, cy, _, _ = capture_region
    fx, fy = int(rx - cx), int(ry - cy)
    fw, fh = int(rw), int(rh)
    h, w = frame_shape[:2]
    x1 = max(0, fx)
    y1 = max(0, fy)
    x2 = min(w, fx + fw)
    y2 = min(h, fy + fh)
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2 - x1, y2 - y1)


def _expand_roi_local(
    roi_local: Optional[Tuple[int, int, int, int]],
    frame_shape: Tuple[int, int, int],
    pad_px: int,
) -> Optional[Tuple[int, int, int, int]]:
    if roi_local is None:
        return None
    x, y, w, h = roi_local
    if w <= 0 or h <= 0:
        return None
    p = max(0, int(pad_px))
    fh, fw = frame_shape[:2]
    x1 = max(0, int(x) - p)
    y1 = max(0, int(y) - p)
    x2 = min(fw, int(x + w) + p)
    y2 = min(fh, int(y + h) + p)
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2 - x1, y2 - y1)


def _build_track_roi_from_bbox(
    det_bbox: Tuple[int, int, int, int],
    frame_shape: Tuple[int, int, int],
    base_margin_px: int,
) -> Tuple[int, int, int, int]:
    bx, by, bw, bh = det_bbox
    fh, fw = frame_shape[:2]
    # Keep a practical motion/jitter buffer for real capture streams.
    adaptive = max(24, int(min(bw, bh) * 0.10))
    margin = min(max(24, int(base_margin_px)), adaptive)
    x = max(0, int(bx) - margin)
    y = max(0, int(by) - margin)
    x2 = min(fw, int(bx + bw) + margin)
    y2 = min(fh, int(by + bh) + margin)
    tw = max(16, x2 - x)
    th = max(16, y2 - y)
    # Hard-stop: tracking roi should not silently become near full screen.
    if tw * th > int(fw * fh * 0.75):
        margin2 = min(32, margin)
        x = max(0, int(bx) - margin2)
        y = max(0, int(by) - margin2)
        x2 = min(fw, int(bx + bw) + margin2)
        y2 = min(fh, int(by + bh) + margin2)
        tw = max(16, x2 - x)
        th = max(16, y2 - y)
    return (x, y, tw, th)


def _roi_local_to_abs(
    roi_local: Optional[Tuple[int, int, int, int]],
    capture_region: Optional[Tuple[int, int, int, int]],
) -> Optional[Tuple[int, int, int, int]]:
    if roi_local is None:
        return None
    if capture_region is None:
        return roi_local
    x, y, w, h = roi_local
    cx, cy, _, _ = capture_region
    return (int(cx + x), int(cy + y), int(w), int(h))


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
        return _roi_abs_to_local(forced_roi_abs, capture_region, frame_shape)
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


def _draw_rect(
    frame: np.ndarray,
    rect: Tuple[int, int, int, int],
    color: Tuple[int, int, int],
    thickness: int = 2,
) -> None:
    x, y, w, h = rect
    x1 = max(0, int(x))
    y1 = max(0, int(y))
    x2 = min(frame.shape[1] - 1, int(x + w))
    y2 = min(frame.shape[0] - 1, int(y + h))
    if x1 >= x2 or y1 >= y2:
        return
    frame[y1 : min(frame.shape[0], y1 + thickness), x1:x2] = color
    frame[max(0, y2 - thickness) : y2, x1:x2] = color
    frame[y1:y2, x1 : min(frame.shape[1], x1 + thickness)] = color
    frame[y1:y2, max(0, x2 - thickness) : x2] = color


def _draw_quad(
    frame: np.ndarray,
    quad: Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float], Tuple[float, float]],
    color: Tuple[int, int, int],
    thickness: int = 2,
) -> None:
    pts = [(int(round(p[0])), int(round(p[1]))) for p in quad]
    h, w = frame.shape[:2]
    for i in range(4):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % 4]
        steps = max(abs(x2 - x1), abs(y2 - y1), 1)
        for s in range(steps + 1):
            x = int(round(x1 + (x2 - x1) * (s / float(steps))))
            y = int(round(y1 + (y2 - y1) * (s / float(steps))))
            x = max(0, min(w - 1, x))
            y = max(0, min(h - 1, y))
            y0 = max(0, y - thickness // 2)
            y1b = min(h, y0 + thickness)
            x0 = max(0, x - thickness // 2)
            x1b = min(w, x0 + thickness)
            frame[y0:y1b, x0:x1b] = color


def _save_debug_image(path: str, frame: np.ndarray) -> None:
    try:
        import cv2  # pylint: disable=import-outside-toplevel

        if cv2.imwrite(path, frame):
            return
    except Exception:
        pass
    np.save(path + ".npy", frame)


def _append_jsonl(path: str, record: Dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def _write_debug_sidecar(path: str, record: Dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)


def _load_json_dict(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _increment_counter(bucket: Dict[str, Any], key: str) -> None:
    bucket[key] = int(bucket.get(key, 0)) + 1


def _update_debug_summary(debug_dir: str, meta: Dict[str, Any]) -> None:
    path = os.path.join(debug_dir, "summary.json")
    summary = _load_json_dict(path)
    summary["total_frames"] = int(summary.get("total_frames", 0)) + 1
    planes = summary.get("planes")
    if not isinstance(planes, dict):
        planes = {}
        summary["planes"] = planes
    control_kinds = summary.get("control_kinds")
    if not isinstance(control_kinds, dict):
        control_kinds = {}
        summary["control_kinds"] = control_kinds
    protocols = summary.get("protocol_paths")
    if not isinstance(protocols, dict):
        protocols = {}
        summary["protocol_paths"] = protocols

    plane = str(meta.get("decoded_plane", "unknown") or "unknown")
    _increment_counter(planes, plane)
    _increment_counter(protocols, str(meta.get("protocol_path_used", "unknown") or "unknown"))
    control_kind = str(meta.get("decoded_control_kind", "") or "")
    if control_kind:
        _increment_counter(control_kinds, control_kind)

    _write_debug_sidecar(path, summary)


def _record_debug_indexes(debug_dir: str, frame_index: int, meta: Dict[str, Any]) -> None:
    frame_base = "frame_{0:05d}".format(frame_index)
    plane = str(meta.get("decoded_plane", "unknown") or "unknown")
    control_kind = str(meta.get("decoded_control_kind", "") or "")
    control_family = str(meta.get("decoded_control_family", "") or "")
    record = {
        "frame_index": int(frame_index),
        "plane": plane,
        "control_family": control_family,
        "control_kind": control_kind,
        "protocol_path_used": str(meta.get("protocol_path_used", "")),
        "decode_error": str(meta.get("decode_error", "")),
        "frame_json": frame_base + ".json",
        "frame_dir": frame_base,
    }
    _append_jsonl(os.path.join(debug_dir, "index_all.jsonl"), record)
    _append_jsonl(os.path.join(debug_dir, "by_plane", plane, "index.jsonl"), record)
    _write_debug_sidecar(
        os.path.join(debug_dir, "by_plane", plane, frame_base + ".json"),
        record,
    )
    if control_kind:
        _append_jsonl(
            os.path.join(debug_dir, "by_control_kind", control_kind, "index.jsonl"),
            record,
        )
        _write_debug_sidecar(
            os.path.join(debug_dir, "by_control_kind", control_kind, frame_base + ".json"),
            record,
        )
    _update_debug_summary(debug_dir, meta)


def _init_debug_meta(
    frame: np.ndarray,
    frame_index: int,
    threshold: int,
    capture_region: Optional[Tuple[int, int, int, int]],
    forced_roi_abs: Optional[Tuple[int, int, int, int]],
    forced_roi_local: Optional[Tuple[int, int, int, int]],
    decode_error: Optional[str],
    selected_block_size: Optional[int],
    protocol_path_used: str,
    detect_mode_used: str,
    det_confidence: float,
    decode_attempt_total: int,
    fallback_hits: int,
) -> Dict[str, Any]:
    return {
        "frame_index": frame_index,
        "frame_shape": [int(frame.shape[1]), int(frame.shape[0])],
        "threshold": int(threshold),
        "capture_region": capture_region,
        "forced_roi_abs": forced_roi_abs,
        "forced_roi_local": forced_roi_local,
        "decode_error": decode_error or "",
        "selected_block_size": selected_block_size if selected_block_size is not None else 0,
        "protocol_path_used": protocol_path_used,
        "detect_mode_used": detect_mode_used,
        "det_confidence": float(det_confidence),
        "decode_attempt_total": int(decode_attempt_total),
        "fallback_hits": int(fallback_hits),
        # Protocol-standard per-frame fields (always present).
        "locator_engine": "",
        "roi_offset": [0, 0],
        "finder_candidates": [],
        "quad_src": [],
        "warp_rmse": 0.0,
        "timing_score": 0.0,
        "confidence": 0.0,
        "fail_reason": "",
        "elapsed_ms": 0.0,
        "legacy_used": False,
        "legacy_elapsed_ms": 0.0,
        "new_fail_reason": "",
        "new_elapsed_ms": 0.0,
        "gray4_failure_class": _classify_gray4_decode_failure(decode_error),
        "gray4_mask_id": -1,
        "gray4_avg_symbol_confidence": 0.0,
        "gray4_payload_low_conf_symbols": 0,
        "gray4_payload_variant_attempts": 0,
        "layered_bootstrap_attempt_count": 0,
        "layered_bootstrap_threshold": 0,
        "layered_bootstrap_vote_margin_min": 0.0,
        "layered_bootstrap_vote_margin_avg": 0.0,
        "layered_control_band_decode_stage": "",
        "layered_control_trace": {},
        "layered_format_attempt_count": 0,
        "layered_format_fallback_attempts": 0,
        "layered_format_fallback_successes": 0,
        "layered_format_primary_threshold": 0,
        "layered_format_primary_threshold_mode": "",
        "layered_format_fallback_threshold": -1,
        "layered_format_vote_margin_min": 0.0,
        "layered_format_vote_margin_avg": 0.0,
        "layered_format_repetition_level": 0,
        "layered_format_coords_count": 0,
        "layered_format_mask_id_guess": -1,
        "layered_format_trace": {},
    }


def _apply_v31_meta_to_debug(
    meta: Dict[str, Any],
    v31_meta: object,
) -> Dict[str, Any]:
    meta["locator_engine"] = getattr(v31_meta, "locator_engine", "")
    meta["new_fail_reason"] = getattr(v31_meta, "new_fail_reason", "")
    meta["new_elapsed_ms"] = float(getattr(v31_meta, "new_elapsed_ms", 0.0))
    meta["legacy_used"] = bool(getattr(v31_meta, "legacy_used", False))
    meta["legacy_elapsed_ms"] = float(getattr(v31_meta, "legacy_elapsed_ms", 0.0))
    meta["confidence"] = float(getattr(v31_meta, "confidence", 0.0))
    meta["fail_reason"] = getattr(v31_meta, "fail_reason", "")
    meta["elapsed_ms"] = float(getattr(v31_meta, "elapsed_ms", 0.0))
    meta["gray4_mask_id"] = int(getattr(v31_meta, "mask_id", -1))
    meta["gray4_avg_symbol_confidence"] = float(
        getattr(v31_meta, "avg_symbol_confidence", 0.0)
    )
    meta["gray4_payload_low_conf_symbols"] = int(
        getattr(v31_meta, "payload_low_conf_symbols", 0)
    )
    meta["gray4_payload_variant_attempts"] = int(
        getattr(v31_meta, "payload_variant_attempts", 0)
    )
    meta["layered_bootstrap_attempt_count"] = int(getattr(v31_meta, "bootstrap_attempt_count", 0))
    meta["layered_bootstrap_threshold"] = int(getattr(v31_meta, "bootstrap_threshold", 0))
    meta["layered_bootstrap_vote_margin_min"] = float(
        getattr(v31_meta, "bootstrap_vote_margin_min", 0.0)
    )
    meta["layered_bootstrap_vote_margin_avg"] = float(
        getattr(v31_meta, "bootstrap_vote_margin_avg", 0.0)
    )
    meta["layered_control_band_decode_stage"] = str(
        getattr(v31_meta, "control_band_decode_stage", "")
    )
    control_trace = getattr(v31_meta, "control_trace", None)
    if isinstance(control_trace, dict):
        meta["layered_control_trace"] = control_trace
    meta["layered_format_attempt_count"] = int(getattr(v31_meta, "format_attempt_count", 0))
    meta["layered_format_fallback_attempts"] = int(
        getattr(v31_meta, "format_fallback_attempts", 0)
    )
    meta["layered_format_fallback_successes"] = int(
        getattr(v31_meta, "format_fallback_successes", 0)
    )
    meta["layered_format_primary_threshold"] = int(
        getattr(v31_meta, "format_primary_threshold", 0)
    )
    meta["layered_format_primary_threshold_mode"] = str(
        getattr(v31_meta, "format_primary_threshold_mode", "")
    )
    meta["layered_format_fallback_threshold"] = int(
        getattr(v31_meta, "format_fallback_threshold", -1)
    )
    meta["layered_format_vote_margin_min"] = float(
        getattr(v31_meta, "format_vote_margin_min", 0.0)
    )
    meta["layered_format_vote_margin_avg"] = float(
        getattr(v31_meta, "format_vote_margin_avg", 0.0)
    )
    meta["layered_format_repetition_level"] = int(
        getattr(v31_meta, "format_repetition_level", 0)
    )
    meta["layered_format_coords_count"] = int(getattr(v31_meta, "format_coords_count", 0))
    meta["layered_format_mask_id_guess"] = int(getattr(v31_meta, "format_mask_id_guess", -1))
    locator_debug = getattr(v31_meta, "locator_debug_artifacts", None)
    if isinstance(locator_debug, dict):
        if (
            isinstance(locator_debug.get("roi_offset"), list)
            and len(locator_debug["roi_offset"]) == 2
        ):
            meta["roi_offset"] = [
                int(locator_debug["roi_offset"][0]),
                int(locator_debug["roi_offset"][1]),
            ]
        for key in (
            "finder_candidates",
            "quad_src",
            "warp_rmse",
            "timing_score",
            "confidence",
            "fail_reason",
        ):
            if key in locator_debug:
                meta[key] = locator_debug[key]
    return locator_debug if isinstance(locator_debug, dict) else {}


def _probe_locator_debug(
    meta: Dict[str, Any],
    frame: np.ndarray,
    track_roi_local: Optional[Tuple[int, int, int, int]],
    forced_roi_local: Optional[Tuple[int, int, int, int]],
    grid_w: int,
    grid_h: int,
    locator_confidence_threshold: float,
) -> Dict[str, Any]:
    probe_roi = track_roi_local if track_roi_local is not None else forced_roi_local
    loc_cfg = LocatorConfig(
        grid_w=int(grid_w),
        grid_h=int(grid_h),
        confidence_threshold=float(locator_confidence_threshold),
    )
    loc = locate_frame(frame=frame, search_roi=probe_roi, config=loc_cfg)
    if isinstance(loc, LocateErrorV31):
        meta["locator_engine"] = "new"
        meta["fail_reason"] = loc.fail_reason.value
        meta["elapsed_ms"] = float(loc.elapsed_ms)
        ldbg = loc.debug_artifacts if isinstance(loc.debug_artifacts, dict) else {}
    else:
        meta["locator_engine"] = "new"
        meta["confidence"] = float(loc.quality.confidence)
        meta["timing_score"] = float(loc.quality.timing_score)
        meta["warp_rmse"] = float(loc.quality.warp_rmse)
        meta["fail_reason"] = "" if loc.fail_reason is None else loc.fail_reason.value
        meta["elapsed_ms"] = float(loc.elapsed_ms)
        ldbg = loc.debug_artifacts if isinstance(loc.debug_artifacts, dict) else {}
    if isinstance(ldbg.get("roi_offset"), list) and len(ldbg["roi_offset"]) == 2:
        meta["roi_offset"] = [int(ldbg["roi_offset"][0]), int(ldbg["roi_offset"][1])]
    if isinstance(ldbg.get("finder_candidates"), list):
        meta["finder_candidates"] = ldbg["finder_candidates"]
    if isinstance(ldbg.get("quad_src"), list):
        meta["quad_src"] = ldbg["quad_src"]
    return ldbg


def _probe_compact_debug(
    meta: Dict[str, Any],
    frame: np.ndarray,
    track_roi_local: Optional[Tuple[int, int, int, int]],
    forced_roi_local: Optional[Tuple[int, int, int, int]],
) -> Dict[str, Any]:
    def _resolve_bbox(
        view: np.ndarray, allow_full_frame: bool
    ) -> Optional[Tuple[int, int, int, int]]:
        bbox = _bbox_from_non_black(view)
        if bbox is not None:
            return bbox
        det = detect_symbol_bbox(view)
        if det is not None:
            return det.bbox
        if allow_full_frame:
            h, w = view.shape[:2]
            if w >= 64 and h >= 64:
                return (0, 0, int(w), int(h))
        return None

    probe_roi = track_roi_local if track_roi_local is not None else forced_roi_local
    if probe_roi is not None:
        x, y, w, h = probe_roi
        x1 = max(0, int(x))
        y1 = max(0, int(y))
        x2 = min(frame.shape[1], int(x + w))
        y2 = min(frame.shape[0], int(y + h))
        if x1 < x2 and y1 < y2:
            view = frame[y1:y2, x1:x2]
            bbox = _resolve_bbox(view, allow_full_frame=True)
            if bbox is not None:
                bx, by, bw, bh = bbox
                mapped = (x1 + bx, y1 + by, bw, bh)
                meta["locator_engine"] = "bbox"
                meta["finder_candidates"] = [{"bbox": [int(v) for v in mapped], "score": 0.85}]
                meta["confidence"] = 0.85
                meta["fail_reason"] = ""
                return {"finder_candidates": meta["finder_candidates"]}
    bbox = _resolve_bbox(frame, allow_full_frame=False)
    if bbox is not None:
        meta["locator_engine"] = "bbox"
        meta["finder_candidates"] = [{"bbox": [int(v) for v in bbox], "score": 0.85}]
        meta["confidence"] = 0.85
        meta["fail_reason"] = ""
        return {"finder_candidates": meta["finder_candidates"]}
    meta["locator_engine"] = "bbox"
    meta["fail_reason"] = "NO_FINDER"
    return {}


def _dump_debug_snapshot(
    debug_dir: str,
    frame_index: int,
    frame: np.ndarray,
    threshold: int,
    forced_roi_local: Optional[Tuple[int, int, int, int]],
    forced_roi_abs: Optional[Tuple[int, int, int, int]],
    capture_region: Optional[Tuple[int, int, int, int]],
    decode_error: Optional[str],
    selected_block_size: Optional[int],
    protocol_path_used: str,
    detect_mode_used: str,
    track_roi_local: Optional[Tuple[int, int, int, int]],
    det_bbox_local: Optional[Tuple[int, int, int, int]],
    det_confidence: float,
    decode_attempt_total: int,
    fallback_hits: int,
    manual_strict: bool = False,
    v31_meta: Optional[object] = None,
    grid_w: int = 160,
    grid_h: int = 96,
    locator_confidence_threshold: float = 0.55,
    control_plane_kinds: Optional[list[str]] = None,
    control_session: Optional[Dict[str, object]] = None,
    control_layout: Optional[Dict[str, object]] = None,
    control_generation: Optional[Dict[str, object]] = None,
    control_generations_seen: Optional[list[int]] = None,
    decoded_chunk_id: Optional[int] = None,
    decoded_payload: Optional[bytes] = None,
    layered_failure_trace: Optional[Dict[str, object]] = None,
) -> None:
    os.makedirs(debug_dir, exist_ok=True)
    raw = frame.copy()
    canvas = frame.copy()
    meta = _init_debug_meta(
        frame=frame,
        frame_index=frame_index,
        threshold=threshold,
        capture_region=capture_region,
        forced_roi_abs=forced_roi_abs,
        forced_roi_local=forced_roi_local,
        decode_error=decode_error,
        selected_block_size=selected_block_size,
        protocol_path_used=protocol_path_used,
        detect_mode_used=detect_mode_used,
        det_confidence=det_confidence,
        decode_attempt_total=decode_attempt_total,
        fallback_hits=fallback_hits,
    )
    locator_debug: Dict[str, Any] = {}
    meta["control_plane_kinds"] = [] if control_plane_kinds is None else list(control_plane_kinds)
    meta["control_session"] = None if control_session is None else dict(control_session)
    meta["control_layout"] = None if control_layout is None else dict(control_layout)
    meta["control_generation"] = None if control_generation is None else dict(control_generation)
    meta["control_generations_seen"] = (
        [] if control_generations_seen is None else [int(v) for v in control_generations_seen]
    )
    meta["decoded_plane"] = "unknown"
    meta["decoded_control_family"] = ""
    meta["decoded_control_kind"] = ""
    if decoded_chunk_id is not None:
        meta["decoded_chunk_id"] = int(decoded_chunk_id)
        control_kind = control_kind_from_wire_chunk_id(decoded_chunk_id)
        if control_kind is not None:
            meta["decoded_plane"] = "control"
            meta["decoded_control_family"] = control_family_for_kind(control_kind)
            meta["decoded_control_kind"] = control_kind
            try:
                if decoded_payload is not None and control_kind == "session":
                    meta["decoded_control_payload"] = decode_session_bootstrap(decoded_payload)
                elif decoded_payload is not None and control_kind == "layout":
                    meta["decoded_control_payload"] = decode_layout_bootstrap(decoded_payload)
                elif decoded_payload is not None and control_kind == "generation":
                    meta["decoded_control_payload"] = decode_generation_control(decoded_payload)
            except Exception:
                meta["decoded_control_payload"] = {"decode_error": "control_payload_parse_failed"}
        elif int(decoded_chunk_id) > 0:
            meta["decoded_plane"] = "data"
    if v31_meta is not None:
        locator_debug = _apply_v31_meta_to_debug(meta=meta, v31_meta=v31_meta)
    if layered_failure_trace is not None:
        meta["layered_control_trace"] = dict(layered_failure_trace)
    elif protocol_path_used == "basic":
        # When decode fails we still run locator once for debug so overlays are visible.
        locator_debug = _probe_locator_debug(
            meta=meta,
            frame=frame,
            track_roi_local=track_roi_local,
            forced_roi_local=forced_roi_local,
            grid_w=grid_w,
            grid_h=grid_h,
            locator_confidence_threshold=locator_confidence_threshold,
        )
    elif protocol_path_used == "compact":
        locator_debug = _probe_compact_debug(
            meta=meta,
            frame=frame,
            track_roi_local=track_roi_local,
            forced_roi_local=forced_roi_local,
        )

    if not manual_strict:
        # Legacy locator debug removed - only basic protocol supported
        meta["locator_bbox_projection"] = None
        meta["locator_confidence_projection"] = 0.0
        meta["locator_bbox_cc"] = None
        meta["locator_confidence_cc"] = 0.0
    else:
        meta["locator_bbox_projection"] = None
        meta["locator_confidence_projection"] = 0.0
        meta["locator_bbox_cc"] = None
        meta["locator_confidence_cc"] = 0.0

    # Probe the basic detector for debug: if forced ROI exists, probe within ROI only.
    if forced_roi_local is not None and not manual_strict:
        fx, fy, fw, fh = forced_roi_local
        x1 = max(0, int(fx))
        y1 = max(0, int(fy))
        x2 = min(frame.shape[1], int(fx + fw))
        y2 = min(frame.shape[0], int(fy + fh))
        if x1 < x2 and y1 < y2:
            probe_view = raw[y1:y2, x1:x2]
            probe = detect_symbol_bbox(probe_view)
            if probe is not None:
                px, py, pw, ph = probe.bbox
                mapped = (x1 + px, y1 + py, pw, ph)
                _draw_rect(canvas, mapped, (0, 0, 255), thickness=2)
                meta["v31_probe_bbox"] = [int(v) for v in mapped]
                meta["v31_probe_confidence"] = float(probe.confidence)
                meta["v31_probe_scope"] = "forced_roi"
            else:
                meta["v31_probe_bbox"] = None
                meta["v31_probe_confidence"] = 0.0
                meta["v31_probe_scope"] = "forced_roi"
        else:
            meta["v31_probe_bbox"] = None
            meta["v31_probe_confidence"] = 0.0
            meta["v31_probe_scope"] = "forced_roi_invalid"
    elif not manual_strict:
        probe = detect_symbol_bbox(raw)
        if probe is not None:
            _draw_rect(canvas, probe.bbox, (0, 0, 255), thickness=2)
            meta["v31_probe_bbox"] = [int(v) for v in probe.bbox]
            meta["v31_probe_confidence"] = float(probe.confidence)
        else:
            meta["v31_probe_bbox"] = None
            meta["v31_probe_confidence"] = 0.0
        meta["v31_probe_scope"] = "full_frame"
    else:
        meta["v31_probe_bbox"] = None
        meta["v31_probe_confidence"] = 0.0
        meta["v31_probe_scope"] = "manual_strict_disabled"

    if forced_roi_local is not None and not manual_strict:
        _draw_rect(canvas, forced_roi_local, (0, 255, 255), thickness=3)
        # Legacy locator debug removed
        meta["locator_bbox_in_forced_roi"] = None
        meta["locator_confidence_in_forced_roi"] = 0.0
    elif forced_roi_local is not None:
        _draw_rect(canvas, forced_roi_local, (0, 255, 255), thickness=3)
        meta["locator_bbox_in_forced_roi"] = None
        meta["locator_confidence_in_forced_roi"] = 0.0

    if track_roi_local is not None:
        _draw_rect(canvas, track_roi_local, (255, 255, 0), thickness=2)
        meta["track_roi_local"] = [int(v) for v in track_roi_local]
        track_abs = _roi_local_to_abs(track_roi_local, capture_region)
        if track_abs is not None:
            meta["track_roi_abs"] = [int(v) for v in track_abs]
        if manual_strict:
            meta["decode_roi_local"] = [int(v) for v in track_roi_local]
            if track_abs is not None:
                meta["decode_roi_abs"] = [int(v) for v in track_abs]
    elif manual_strict and forced_roi_local is not None:
        meta["decode_roi_local"] = [int(v) for v in forced_roi_local]
        forced_abs = _roi_local_to_abs(forced_roi_local, capture_region)
        if forced_abs is not None:
            meta["decode_roi_abs"] = [int(v) for v in forced_abs]

    if det_bbox_local is not None:
        _draw_rect(canvas, det_bbox_local, (0, 0, 255), thickness=3)
        meta["det_bbox_local"] = [int(v) for v in det_bbox_local]
        det_abs = _roi_local_to_abs(det_bbox_local, capture_region)
        if det_abs is not None:
            meta["det_bbox_abs"] = [int(v) for v in det_abs]

    stem = os.path.join(debug_dir, "frame_{0:05d}".format(frame_index))
    _save_debug_image(stem + ".raw.png", raw)
    _save_debug_image(stem + ".annotated.png", canvas)
    _save_debug_image(stem + ".png", canvas)
    with open(stem + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    _record_debug_indexes(debug_dir=debug_dir, frame_index=frame_index, meta=meta)

    # Protocol-standard debug artifact set.
    frame_dir = os.path.join(debug_dir, "frame_{0:05d}".format(frame_index))
    os.makedirs(frame_dir, exist_ok=True)
    _save_debug_image(os.path.join(frame_dir, "frame_raw.png"), raw)

    finder_canvas = raw.copy()
    if isinstance(locator_debug, dict):
        for cand in locator_debug.get("finder_candidates", []):
            if (
                isinstance(cand, dict)
                and isinstance(cand.get("bbox"), list)
                and len(cand["bbox"]) == 4
            ):
                bbox_tuple = tuple(int(v) for v in cand["bbox"])
                if len(bbox_tuple) == 4:
                    _draw_rect(finder_canvas, bbox_tuple, (0, 0, 255), thickness=2)  # type: ignore[arg-type]
    _save_debug_image(os.path.join(frame_dir, "finder_candidates.png"), finder_canvas)

    quad_canvas = raw.copy()
    if isinstance(locator_debug, dict):
        quad_src = locator_debug.get("quad_src")
        if isinstance(quad_src, list) and len(quad_src) == 4:
            try:
                q = tuple((float(p[0]), float(p[1])) for p in quad_src)
                if len(q) == 4:
                    _draw_quad(quad_canvas, q, (0, 255, 0), thickness=2)  # type: ignore[arg-type]
            except Exception:
                pass
    _save_debug_image(os.path.join(frame_dir, "quad_selected.png"), quad_canvas)

    crop_rect = det_bbox_local
    if crop_rect is None:
        probe_bbox = meta.get("v31_probe_bbox")
        if isinstance(probe_bbox, list) and len(probe_bbox) == 4:
            crop_rect = tuple(int(v) for v in probe_bbox)
    if crop_rect is None:
        finder_candidates = locator_debug.get("finder_candidates") if isinstance(locator_debug, dict) else None
        if isinstance(finder_candidates, list) and finder_candidates:
            first = finder_candidates[0]
            if isinstance(first, dict):
                bbox = first.get("bbox")
                if isinstance(bbox, list) and len(bbox) == 4:
                    crop_rect = tuple(int(v) for v in bbox)
    if crop_rect is not None:
        x, y, w, h = crop_rect
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(raw.shape[1], x + w)
        y2 = min(raw.shape[0], y + h)
        if x1 < x2 and y1 < y2:
            _save_debug_image(os.path.join(frame_dir, "bbox_crop.png"), raw[y1:y2, x1:x2].copy())

    warp = getattr(v31_meta, "locator_warped_preview", None) if v31_meta is not None else None
    if warp is not None and isinstance(warp, np.ndarray):
        warp_img = warp.copy()
        _save_debug_image(os.path.join(frame_dir, "warp.png"), warp_img)
        grid_overlay = warp_img.copy()
        sample_overlay = warp_img.copy()
        if isinstance(locator_debug, dict):
            grid_bbox = locator_debug.get("grid_bbox_std")
            if isinstance(grid_bbox, list) and len(grid_bbox) == 4:
                gx, gy, gw, gh = [int(v) for v in grid_bbox]
                _draw_rect(grid_overlay, (gx, gy, gw, gh), (255, 0, 0), thickness=2)
                try:
                    gwh = getattr(v31_meta, "grid_size", "160x96")
                    gx_count, gy_count = [int(p) for p in str(gwh).lower().split("x")]
                    step_x = max(1, gx_count // 20)
                    step_y = max(1, gy_count // 12)
                    cell_w = float(gw) / float(max(1, gx_count))
                    cell_h = float(gh) / float(max(1, gy_count))
                    for j in range(0, gy_count, step_y):
                        for i in range(0, gx_count, step_x):
                            px = int(round(gx + (i + 0.5) * cell_w))
                            py = int(round(gy + (j + 0.5) * cell_h))
                            _draw_rect(
                                sample_overlay, (px - 1, py - 1, 3, 3), (0, 255, 255), thickness=1
                            )
                except Exception:
                    pass
        _save_debug_image(os.path.join(frame_dir, "grid_overlay.png"), grid_overlay)
        _save_debug_image(os.path.join(frame_dir, "sample_points.png"), sample_overlay)
    else:
        _save_debug_image(os.path.join(frame_dir, "warp.png"), raw)
        _save_debug_image(os.path.join(frame_dir, "grid_overlay.png"), raw)
        _save_debug_image(os.path.join(frame_dir, "sample_points.png"), raw)


def _should_dump_debug_snapshot(
    debug_dir: Optional[str],
    debug_written: int,
    debug_max_frames: int,
    now: float,
    debug_next_ts: float,
    threshold: Optional[int],
) -> bool:
    return bool(
        debug_dir
        and debug_written < debug_max_frames
        and now >= debug_next_ts
        and threshold is not None
    )


def _maybe_dump_debug_snapshot(
    now: float,
    debug_dir: Optional[str],
    debug_written: int,
    debug_max_frames: int,
    debug_next_ts: float,
    debug_interval: float,
    debug_time_sum: float,
    debug_time_count: int,
    threshold: Optional[int],
    dump_kwargs: Dict[str, Any],
) -> Tuple[int, float, float, int]:
    if not _should_dump_debug_snapshot(
        debug_dir=debug_dir,
        debug_written=debug_written,
        debug_max_frames=debug_max_frames,
        now=now,
        debug_next_ts=debug_next_ts,
        threshold=threshold,
    ):
        return debug_written, debug_next_ts, debug_time_sum, debug_time_count

    t_dbg0 = time.perf_counter()
    _dump_debug_snapshot(
        debug_dir=cast(str, debug_dir),
        threshold=int(cast(int, threshold)),
        **dump_kwargs,
    )
    debug_time_sum += max(0.0, time.perf_counter() - t_dbg0)
    debug_time_count += 1
    debug_written += 1
    debug_next_ts = now + max(0.1, debug_interval)
    return debug_written, debug_next_ts, debug_time_sum, debug_time_count


def main(argv=None):
    args = build_parser().parse_args(argv)
    roi_policy = RoiPolicy.from_args(args)
    roi_policy.apply_to_args(args)
    if args.source == "screen" and args.window_title and not (args.roi or args.region):
        print(
            "warning: --window-title is currently not used for real window lookup; "
            "capture will fallback to full monitor. "
            "Use --roi x,y,w,h or --roi-interactive for reliable decode."
        )

    if args.block_size == "auto":
        block_size_candidates = [6, 8, 4]
    else:
        block_size_candidates = [int(args.block_size)]
    selected_block_size = None  # type: Optional[int]
    grid_w, grid_h = _parse_module_grid(args.module_grid)
    grid_candidates = [(grid_w, grid_h), (160, 96), (176, 100), (192, 108), (224, 126)]
    uniq = []
    seen = set()
    for g in grid_candidates:
        if g in seen:
            continue
        seen.add(g)
        uniq.append(g)
    grid_candidates = uniq

    cli_roi = _parse_region(args.roi) or _parse_region(args.region)
    profile_roi = load_profile(args.roi_profile) if args.roi_profile else None

    forced_roi = cli_roi or profile_roi
    if forced_roi is not None:
        forced_roi = _ensure_roi_valid(forced_roi)

    if roi_policy.requires_manual_roi(forced_roi=forced_roi):
        raise ValueError("manual roi-mode requires --roi/--roi-profile or --roi-interactive")

    stats = TransferStats()
    stats.set_roi_mode(roi_policy.report_mode)
    if (
        args.source == "screen"
        and roi_policy.mode == "manual"
        and forced_roi is None
        and roi_policy.interactive
    ):
        stats.mark_manual_select_attempt()
        selected = select_region(get_monitor_region(args.monitor_index))
        if selected is None:
            raise RuntimeError("manual roi selection canceled")
        forced_roi = _ensure_roi_valid(selected)
        stats.mark_manual_roi(switched=False)
        if args.roi_profile:
            save_profile(args.roi_profile, forced_roi, args.monitor_index)

    source = _build_source(args, forced_roi)
    if args.debug_dir and isinstance(source, ScreenCapture):
        # Debug mode should not be throttled by frame dedup; otherwise
        # mostly-static captures may produce almost no snapshots.
        source.frame_diff_threshold = 0.0
    if args.debug_dir:
        os.makedirs(args.debug_dir, exist_ok=True)
        print(
            "debug enabled: dir={0} interval={1}s max_frames={2}".format(
                args.debug_dir,
                args.debug_interval,
                args.debug_max_frames,
            )
        )
    assembler = ChunkAssembler()

    threshold = None
    start = time.time()
    last_good = start
    next_stats_ts = start + max(0.1, args.stats_interval)

    final_report = None  # type: Optional[dict]
    auto_fail_count = 0
    manual_attempts = 0
    frame_index = 0
    debug_next_ts = start
    debug_written = 0
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
    protocol_path_used = args.protocol
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
    protocol_report_adapter = make_protocol_report_adapter(args.protocol)
    decode_time_sum = 0.0
    decode_time_count = 0
    debug_time_sum = 0.0
    debug_time_count = 0
    replay_mode = args.source == "replay"
    v3_track_roi = None
    v3_fail_streak = 0
    v3_mode = "full" if (args.detect_mode == "full" or replay_mode) else "track"
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
        report["avg_debug_dump_ms"] = (debug_time_sum / float(max(1, debug_time_count))) * 1000.0
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
        if args.protocol not in ("gray4", "layered"):
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
        if args.protocol == "layered":
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
        if args.protocol == "layered":
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
        source=args.source,
        forced_roi=forced_roi,
    )
    use_pipeline = _should_use_pipeline(
        source=args.source,
        protocol=args.protocol,
        debug_dir=args.debug_dir,
        needs_runtime_roi_selection=needs_runtime_roi_selection,
    )
    if args.debug_dir and args.source == "screen":
        print(
            "debug-dir set: forcing legacy loop (pipeline disabled) to emit debug snapshots"
        )
    if needs_runtime_roi_selection:
        print("select-region with auto_then_manual requires legacy loop for runtime ROI selection")
    if use_pipeline:
        num_workers = args.decode_workers if args.decode_workers > 0 else None
        grid_w, grid_h = _parse_module_grid(args.module_grid)
        guard_band, corner_size = _protocol_geometry(args.protocol)
        pipeline_seed_roi_local = _build_pipeline_seed_roi_local(source, forced_roi)
        pipeline = ScreenLiveRuntime(
            capture=source,
            assembler=assembler,
            decode_workers=1 if num_workers is None else num_workers,
            prep_process=args.prep_process,
            capture_fps=args.capture_fps,
            capture_dump_dir=args.capture_dump_dir,
            capture_dump_max_frames=args.capture_dump_max_frames,
            protocol=args.protocol,
            grid_w=grid_w,
            grid_h=grid_h,
            guard_band=guard_band,
            corner_size=corner_size,
            locator_engine=args.locator_engine,
            locator_confidence_threshold=args.locator_confidence_threshold,
            initial_search_roi=pipeline_seed_roi_local,
        )
        print(
            "screen live runtime: protocol={0} workers={1} prep={2} capture_fps={3} seed_roi={4}".format(
                args.protocol,
                1 if num_workers is None else num_workers,
                args.prep_process,
                args.capture_fps,
                "none"
                if pipeline_seed_roi_local is None
                else "{0},{1},{2},{3}".format(*pipeline_seed_roi_local),
            )
        )
        pipeline.start()
        try:
            deadline = (start + args.max_seconds) if args.max_seconds > 0 else None
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
                    _write_report(args.report_json, final_report)
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
                elif now - last_assembled_ts > args.max_idle_seconds and assembled > 0:
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
                    _write_report(args.report_json, final_report)
                    print("receiver timeout: no new chunks for {0}s".format(args.max_idle_seconds))
                    return 2
                elif assembled == 0 and now - start > args.max_idle_seconds:
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
                    _write_report(args.report_json, final_report)
                    print(
                        "receiver timeout: no valid frames for {0}s".format(args.max_idle_seconds)
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
                    next_stats_ts = now + max(0.1, args.stats_interval)

                if pipeline.done_event.wait(timeout=0.2):
                    break

            pipeline.check_errors()
            payload_bytes = assembler.payload()
            if assembler.manifest is None:
                raise RuntimeError("manifest not received")
            output_path = restore_payload(payload_bytes, assembler.manifest, args.output_dir)
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
            _write_report(args.report_json, final_report)
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
                _write_report(args.report_json, report)
        return 1
    # ── Legacy single-thread mode ────────────────────────────────────────────

    try:
        for frame in source.iter_frames():
            now = time.time()
            frame_index += 1
            frame_v31_meta = None
            capture_region = getattr(source, "active_region", None)
            forced_roi_local = _roi_abs_to_local(forced_roi, capture_region, frame.shape)
            manual_mode_now = roi_policy.manual_active(stats)
            manual_decode_roi_local = (
                _expand_roi_local(forced_roi_local, frame.shape, roi_policy.pad_px)
                if manual_mode_now
                else forced_roi_local
            )
            if (
                (not replay_mode)
                and args.detect_mode != "full"
                and v3_track_roi is None
                and manual_decode_roi_local is not None
            ):
                v3_track_roi = manual_decode_roi_local

            if args.max_seconds > 0 and now - start > args.max_seconds:
                final_report = cast(
                    Dict[str, object], dict(stats.finalize(output_size_bytes=0, ts=now))
                )
                final_report["status"] = "timeout_max_seconds"
                _attach_v3_metrics(final_report)
                _attach_missing_chunks_state(final_report)
                _attach_protocol_debug(final_report)
                _write_report(args.report_json, final_report)
                print("receiver timeout: max-seconds reached")
                return 2

            if now - last_good > args.max_idle_seconds:
                final_report = cast(
                    Dict[str, object], dict(stats.finalize(output_size_bytes=0, ts=now))
                )
                final_report["status"] = "timeout_idle"
                _attach_v3_metrics(final_report)
                _attach_missing_chunks_state(final_report)
                _attach_protocol_debug(final_report)
                _write_report(args.report_json, final_report)
                print("receiver timeout: no valid frames for {0}s".format(args.max_idle_seconds))
                return 2

            if threshold is None:
                # Auto threshold - use simple default for basic protocol
                threshold = 128
                print("using default threshold={0}".format(threshold))

            # manual mode selector on first frame if no roi yet.
            if roi_policy.mode == "manual" and forced_roi is None and roi_policy.interactive:
                stats.mark_manual_select_attempt()
                selected = select_region(get_monitor_region(args.monitor_index))
                if selected is None:
                    raise RuntimeError("manual roi selection canceled")
                forced_roi = _ensure_roi_valid(selected)
                forced_roi_local = _roi_abs_to_local(forced_roi, capture_region, frame.shape)
                manual_decode_roi_local = _expand_roi_local(
                    forced_roi_local, frame.shape, roi_policy.pad_px
                )
                v3_track_roi = manual_decode_roi_local
                stats.mark_manual_roi(switched=False)
                if args.roi_profile:
                    save_profile(args.roi_profile, forced_roi, args.monitor_index)

            try:
                t_decode0 = time.perf_counter()
                if args.protocol in ("basic", "compact", "gray4", "layered"):
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
                        decode_frame_layered if args.protocol == "layered" else
                        decode_frame_gray4 if args.protocol == "gray4" else
                        decode_frame_compact if args.protocol == "compact" else decode_frame_basic
                    )
                    guard_band, corner_size = _protocol_geometry(args.protocol)
                    for gw, gh in grid_candidates:
                        decode_attempt_total += 1
                        try:
                            if args.protocol == "layered" and layered_locked_geometry is not None:
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
                                    locator_engine=args.locator_engine,
                                    locator_confidence_threshold=args.locator_confidence_threshold,
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
                            if args.protocol == "layered" and layered_locked_geometry is not None:
                                geometry_reuse_fail_count += 1
                                layered_locked_fail_streak += 1
                                if layered_locked_fail_streak >= layered_locked_fail_reacquire_threshold:
                                    layered_locked_geometry = None
                                    layered_locked_fail_streak = 0
                                    layered_locked_geometry_age = 0
                                continue
                            if args.protocol == "layered":
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
                                        locator_engine=args.locator_engine,
                                        locator_confidence_threshold=args.locator_confidence_threshold,
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
                    if args.protocol == "layered":
                        trace = getattr(meta31, "control_trace", None)
                        if isinstance(trace, dict):
                            _accumulate_layered_control_trace(trace, is_failure=False)
                    protocol_path_used = args.protocol
                    last_det_bbox = meta31.det_bbox
                    last_det_confidence = float(meta31.det_confidence)
                    locator_new_fail_reason = meta31.new_fail_reason
                    locator_new_elapsed_ms = float(meta31.new_elapsed_ms)
                    locator_legacy_used = bool(meta31.legacy_used)
                    locator_legacy_elapsed_ms = float(meta31.legacy_elapsed_ms)
                    v3_fail_streak = 0
                    if args.protocol == "layered":
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
                            v3_track_roi = _build_track_roi_from_bbox(
                                (bx, by, bw, bh),
                                frame.shape,
                                args.track_margin_px,
                            )
                    if args.detect_mode != "full" and not replay_mode:
                        v3_mode = "track"
                else:
                    raise ValueError(
                        f"Protocol '{args.protocol}' not supported, use 'basic', 'compact', 'gray4', or 'layered'"
                    )
                auto_fail_count = 0
                last_decode_error = None
                if args.protocol in ("gray4", "layered"):
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
                    if args.protocol in ("gray4", "layered"):
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
                        if args.protocol == "layered":
                            layered_detail = _classify_layered_decode_failure_detail(last_decode_error)
                            if layered_detail in layered_failure_counts:
                                layered_failure_counts[layered_detail] += 1
                            trace = getattr(last_exc, "trace", None)
                            if isinstance(trace, dict):
                                layered_failure_trace = dict(trace)
                                _accumulate_layered_control_trace(
                                    trace, is_failure=(layered_detail == "control_prefix")
                                )
                    if args.protocol in ("basic", "compact"):
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
                        selected = select_region(get_monitor_region(args.monitor_index))
                        if selected is not None:
                            forced_roi = _ensure_roi_valid(selected)
                            stats.mark_manual_roi(switched=True)
                            forced_roi_local = _roi_abs_to_local(
                                forced_roi, capture_region, frame.shape
                            )
                            manual_decode_roi_local = _expand_roi_local(
                                forced_roi_local, frame.shape, roi_policy.pad_px
                            )
                            v3_track_roi = manual_decode_roi_local
                            auto_fail_count = 0
                            if args.roi_profile:
                                save_profile(args.roi_profile, forced_roi, args.monitor_index)
                    if now >= next_stats_ts:
                        _print_stats(stats.snapshot(ts=now), assembler.missing_count())
                        next_stats_ts = now + max(0.1, args.stats_interval)
                    debug_written, debug_next_ts, debug_time_sum, debug_time_count = (
                        _maybe_dump_debug_snapshot(
                            now=now,
                            debug_dir=args.debug_dir,
                            debug_written=debug_written,
                            debug_max_frames=args.debug_max_frames,
                            debug_next_ts=debug_next_ts,
                            debug_interval=args.debug_interval,
                            debug_time_sum=debug_time_sum,
                            debug_time_count=debug_time_count,
                            threshold=threshold,
                            dump_kwargs={
                                "frame_index": frame_index,
                                "frame": frame,
                                "forced_roi_local": forced_roi_local,
                                "forced_roi_abs": forced_roi,
                                "capture_region": capture_region,
                                "decode_error": last_decode_error,
                                "selected_block_size": selected_block_size,
                                "protocol_path_used": protocol_path_used,
                                "detect_mode_used": v3_mode,
                                "track_roi_local": v3_track_roi,
                                "det_bbox_local": last_det_bbox,
                                "det_confidence": last_det_confidence,
                                "decode_attempt_total": decode_attempt_total,
                                "fallback_hits": fallback_hits,
                                "manual_strict": roi_policy.manual_active(stats),
                                "v31_meta": frame_v31_meta,
                                "grid_w": grid_w,
                                "grid_h": grid_h,
                                "locator_confidence_threshold": args.locator_confidence_threshold,
                                "layered_failure_trace": layered_failure_trace,
                                **_debug_control_plane_state(),
                            },
                        )
                    )
                    continue

            debug_written, debug_next_ts, debug_time_sum, debug_time_count = (
                _maybe_dump_debug_snapshot(
                    now=now,
                    debug_dir=args.debug_dir,
                    debug_written=debug_written,
                    debug_max_frames=args.debug_max_frames,
                    debug_next_ts=debug_next_ts,
                    debug_interval=args.debug_interval,
                    debug_time_sum=debug_time_sum,
                    debug_time_count=debug_time_count,
                    threshold=threshold,
                    dump_kwargs={
                        "frame_index": frame_index,
                        "frame": frame,
                        "forced_roi_local": forced_roi_local,
                        "forced_roi_abs": forced_roi,
                        "capture_region": capture_region,
                        "decode_error": last_decode_error,
                        "selected_block_size": selected_block_size,
                        "protocol_path_used": protocol_path_used,
                        "detect_mode_used": v3_mode,
                        "track_roi_local": v3_track_roi,
                        "det_bbox_local": last_det_bbox,
                        "det_confidence": last_det_confidence,
                        "decode_attempt_total": decode_attempt_total,
                        "fallback_hits": fallback_hits,
                        "manual_strict": roi_policy.manual_active(stats),
                        "v31_meta": frame_v31_meta,
                        "grid_w": grid_w,
                        "grid_h": grid_h,
                        "locator_confidence_threshold": args.locator_confidence_threshold,
                        "layered_failure_trace": None,
                        **_debug_control_plane_state(),
                        "decoded_chunk_id": int(header.chunk_id),
                        "decoded_payload": payload,
                    },
                )
            )

            is_data_frame = int(header.frame_type) == int(FRAME_DATA)

            if not is_data_frame:
                if first_new_chunk_ts is None:
                    startup_sync_frames_decoded += 1
                stats.on_frame(decoded_ok=True, payload_len=0, ts=now)
                if now >= next_stats_ts:
                    _print_stats(stats.snapshot(ts=now), assembler.missing_count())
                    next_stats_ts = now + max(0.1, args.stats_interval)
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
                next_stats_ts = now + max(0.1, args.stats_interval)

            if assembler.complete():
                payload_bytes = assembler.payload()
                if assembler.manifest is None:
                    continue
                output_path = restore_payload(payload_bytes, assembler.manifest, args.output_dir)
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
                _write_report(args.report_json, final_report)
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
        _write_report(args.report_json, final_report)
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
            _write_report(args.report_json, report)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
