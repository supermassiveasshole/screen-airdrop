"""Debug metadata building utilities."""

import json
import os
from typing import Any, Dict, Optional, Tuple

import numpy as np


class DebugMetadataBuilder:
    """Builds and manages debug metadata for frames."""

    @staticmethod
    def init_debug_meta(
        frame: np.ndarray,
        frame_index: int,
        threshold: int,
        capture_region: Optional[Tuple[int, int, int, int]],
        forced_roi_abs: Optional[Tuple[int, int, int, int]],
        forced_roi_local: Optional[Tuple[int, int, int, int]],
        decode_error: Optional[str],
        protocol: str,
    ) -> Dict[str, Any]:
        """Initialize debug metadata dict.

        Args:
            frame: Input frame
            frame_index: Frame index
            threshold: Binarization threshold
            capture_region: Capture region
            forced_roi_abs: Forced ROI in absolute coordinates
            forced_roi_local: Forced ROI in local coordinates
            decode_error: Decode error string
            protocol: Protocol name

        Returns:
            Debug metadata dict
        """
        h, w = frame.shape[:2]
        meta: Dict[str, Any] = {
            "frame_index": int(frame_index),
            "frame_w": int(w),
            "frame_h": int(h),
            "threshold": int(threshold),
            "decode_error": str(decode_error) if decode_error else "",
        }
        if capture_region is not None:
            meta["capture_region"] = [int(v) for v in capture_region]
        if forced_roi_abs is not None:
            meta["forced_roi_abs"] = [int(v) for v in forced_roi_abs]
        if forced_roi_local is not None:
            meta["forced_roi_local"] = [int(v) for v in forced_roi_local]

        # Protocol-specific fields
        if protocol == "gray4":
            meta["gray4_decode_path"] = ""
            meta["gray4_decode_error"] = ""
            meta["gray4_elapsed_ms"] = 0.0
        elif protocol == "layered":
            meta["layered_decode_path"] = ""
            meta["layered_decode_error"] = ""
            meta["layered_elapsed_ms"] = 0.0
            meta["layered_bootstrap_ok"] = False
            meta["layered_body_ok"] = False

        return meta

    @staticmethod
    def apply_v31_meta_to_debug(
        meta: Dict[str, Any],
        v31_meta: Dict[str, Any],
        protocol: str,
    ) -> None:
        """Apply v31 metadata to debug dict.

        Args:
            meta: Debug metadata dict to populate
            v31_meta: V31 metadata from decoder
            protocol: Protocol name
        """
        # Locator engine info
        if "locator_engine" in v31_meta:
            meta["locator_engine"] = str(v31_meta["locator_engine"])
        if "confidence" in v31_meta:
            meta["confidence"] = float(v31_meta["confidence"])
        if "timing_score" in v31_meta:
            meta["timing_score"] = float(v31_meta["timing_score"])
        if "warp_rmse" in v31_meta:
            meta["warp_rmse"] = float(v31_meta["warp_rmse"])
        if "fail_reason" in v31_meta:
            meta["fail_reason"] = str(v31_meta["fail_reason"])
        if "elapsed_ms" in v31_meta:
            meta["elapsed_ms"] = float(v31_meta["elapsed_ms"])
        if "roi_offset" in v31_meta:
            meta["roi_offset"] = v31_meta["roi_offset"]
        if "finder_candidates" in v31_meta:
            meta["finder_candidates"] = v31_meta["finder_candidates"]
        if "quad_src" in v31_meta:
            meta["quad_src"] = v31_meta["quad_src"]

        # Protocol-specific fields
        if protocol == "gray4":
            if "gray4_decode_path" in v31_meta:
                meta["gray4_decode_path"] = str(v31_meta["gray4_decode_path"])
            if "gray4_decode_error" in v31_meta:
                meta["gray4_decode_error"] = str(v31_meta["gray4_decode_error"])
            if "gray4_elapsed_ms" in v31_meta:
                meta["gray4_elapsed_ms"] = float(v31_meta["gray4_elapsed_ms"])
        elif protocol == "layered":
            if "layered_decode_path" in v31_meta:
                meta["layered_decode_path"] = str(v31_meta["layered_decode_path"])
            if "layered_decode_error" in v31_meta:
                meta["layered_decode_error"] = str(v31_meta["layered_decode_error"])
            if "layered_elapsed_ms" in v31_meta:
                meta["layered_elapsed_ms"] = float(v31_meta["layered_elapsed_ms"])
            if "layered_bootstrap_ok" in v31_meta:
                meta["layered_bootstrap_ok"] = bool(v31_meta["layered_bootstrap_ok"])
            if "layered_body_ok" in v31_meta:
                meta["layered_body_ok"] = bool(v31_meta["layered_body_ok"])

    @staticmethod
    def record_debug_indexes(
        debug_dir: str, frame_index: int, meta: Dict[str, Any]
    ) -> None:
        """Record debug indexes for frame.

        Args:
            debug_dir: Debug directory
            frame_index: Frame index
            meta: Debug metadata dict
        """
        frame_base = f"frame_{frame_index:05d}"
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
        DebugMetadataBuilder._append_jsonl(
            os.path.join(debug_dir, "index_all.jsonl"), record
        )
        DebugMetadataBuilder._append_jsonl(
            os.path.join(debug_dir, "by_plane", plane, "index.jsonl"), record
        )
        DebugMetadataBuilder._write_debug_sidecar(
            os.path.join(debug_dir, "by_plane", plane, frame_base + ".json"),
            record,
        )
        if control_kind:
            DebugMetadataBuilder._append_jsonl(
                os.path.join(debug_dir, "by_control_kind", control_kind, "index.jsonl"),
                record,
            )
            DebugMetadataBuilder._write_debug_sidecar(
                os.path.join(
                    debug_dir, "by_control_kind", control_kind, frame_base + ".json"
                ),
                record,
            )
        DebugMetadataBuilder._update_debug_summary(debug_dir, meta)

    @staticmethod
    def _append_jsonl(path: str, record: Dict[str, Any]) -> None:
        """Append record to JSONL file."""
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    @staticmethod
    def _write_debug_sidecar(path: str, record: Dict[str, Any]) -> None:
        """Write debug sidecar JSON file."""
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _load_json_dict(path: str) -> Dict[str, Any]:
        """Load JSON dict from file."""
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _increment_counter(bucket: Dict[str, Any], key: str) -> None:
        """Increment counter in bucket."""
        bucket[key] = int(bucket.get(key, 0)) + 1

    @staticmethod
    def _update_debug_summary(debug_dir: str, meta: Dict[str, Any]) -> None:
        """Update debug summary file."""
        path = os.path.join(debug_dir, "summary.json")
        summary = DebugMetadataBuilder._load_json_dict(path)
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
        DebugMetadataBuilder._increment_counter(planes, plane)
        DebugMetadataBuilder._increment_counter(
            protocols, str(meta.get("protocol_path_used", "unknown") or "unknown")
        )
        control_kind = str(meta.get("decoded_control_kind", "") or "")
        if control_kind:
            DebugMetadataBuilder._increment_counter(control_kinds, control_kind)

        DebugMetadataBuilder._write_debug_sidecar(path, summary)
