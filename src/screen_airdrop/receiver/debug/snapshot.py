"""Debug snapshot generation and management."""

import os
import time
from typing import Any, Dict, Optional, Tuple, cast

import numpy as np

from screen_airdrop.receiver.debug.drawing import FrameDrawer
from screen_airdrop.receiver.debug.metadata import DebugMetadataBuilder
from screen_airdrop.receiver.detector_basic import detect_symbol_bbox


def _roi_local_to_abs(
    roi_local: Tuple[int, int, int, int],
    capture_region: Optional[Tuple[int, int, int, int]],
) -> Optional[Tuple[int, int, int, int]]:
    """Convert local ROI to absolute coordinates."""
    if capture_region is None:
        return roi_local
    x, y, w, h = roi_local
    cx, cy, _, _ = capture_region
    return (cx + x, cy + y, w, h)


class DebugSnapshotManager:
    """Manages debug snapshot generation and timing."""

    def __init__(
        self,
        debug_dir: str,
        debug_max_frames: int = 100,
        debug_interval: float = 0.5,
    ):
        """Initialize snapshot manager.

        Args:
            debug_dir: Debug output directory
            debug_max_frames: Maximum number of frames to capture
            debug_interval: Minimum interval between snapshots in seconds
        """
        self.debug_dir = debug_dir
        self.debug_max_frames = debug_max_frames
        self.debug_interval = debug_interval
        self.debug_written = 0
        self.debug_next_ts = 0.0
        self.debug_time_sum = 0.0
        self.debug_time_count = 0
        self.drawer = FrameDrawer()
        self.metadata_builder = DebugMetadataBuilder()

    def should_dump(
        self,
        now: float,
        threshold: Optional[int],
    ) -> bool:
        """Check if a snapshot should be dumped.

        Args:
            now: Current timestamp
            threshold: Binarization threshold (None if not available)

        Returns:
            True if snapshot should be dumped
        """
        return bool(
            self.debug_written < self.debug_max_frames
            and now >= self.debug_next_ts
            and threshold is not None
        )

    def maybe_dump(
        self,
        now: float,
        threshold: Optional[int],
        dump_kwargs: Dict[str, Any],
    ) -> None:
        """Maybe dump a debug snapshot.

        Args:
            now: Current timestamp
            threshold: Binarization threshold
            dump_kwargs: Keyword arguments for dump_snapshot
        """
        if not self.should_dump(now, threshold):
            return

        t_dbg0 = time.perf_counter()
        self.dump_snapshot(
            threshold=int(cast(int, threshold)),
            **dump_kwargs,
        )
        self.debug_time_sum += max(0.0, time.perf_counter() - t_dbg0)
        self.debug_time_count += 1
        self.debug_written += 1
        self.debug_next_ts = now + max(0.1, self.debug_interval)

    def dump_snapshot(
        self,
        frame_index: int,
        frame: np.ndarray,
        threshold: int,
        forced_roi_local: Optional[Tuple[int, int, int, int]],
        forced_roi_abs: Optional[Tuple[int, int, int, int]],
        capture_region: Optional[Tuple[int, int, int, int]],
        decode_error: Optional[str],
        protocol_path_used: str,
        track_roi_local: Optional[Tuple[int, int, int, int]],
        det_bbox_local: Optional[Tuple[int, int, int, int]],
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
        protocol: str = "basic",
    ) -> None:
        """Dump a debug snapshot.

        Args:
            frame_index: Frame index
            frame: Input frame
            threshold: Binarization threshold
            forced_roi_local: Forced ROI in local coordinates
            forced_roi_abs: Forced ROI in absolute coordinates
            capture_region: Capture region
            decode_error: Decode error string
            protocol_path_used: Protocol path used
            track_roi_local: Tracking ROI in local coordinates
            det_bbox_local: Detection bbox in local coordinates
            manual_strict: Manual strict mode
            v31_meta: V31 metadata from decoder
            grid_w: Grid width
            grid_h: Grid height
            locator_confidence_threshold: Locator confidence threshold
            control_plane_kinds: Control plane kinds
            control_session: Control session
            control_layout: Control layout
            control_generation: Control generation
            control_generations_seen: Control generations seen
            decoded_chunk_id: Decoded chunk ID
            decoded_payload: Decoded payload
            layered_failure_trace: Layered failure trace
            protocol: Protocol name
        """
        from screen_airdrop.common.control_plane import (
            control_family_for_kind,
            control_kind_from_wire_chunk_id,
            decode_generation_control,
            decode_layout_bootstrap,
            decode_session_bootstrap,
        )
        from screen_airdrop.receiver.debug.probes import (
            probe_compact_debug,
            probe_locator_debug,
        )

        os.makedirs(self.debug_dir, exist_ok=True)
        raw = frame.copy()
        canvas = frame.copy()

        # Initialize metadata
        meta = self.metadata_builder.init_debug_meta(
            frame=frame,
            frame_index=frame_index,
            threshold=threshold,
            capture_region=capture_region,
            forced_roi_abs=forced_roi_abs,
            forced_roi_local=forced_roi_local,
            decode_error=decode_error,
            protocol=protocol,
        )

        # Add legacy fields for compatibility
        meta["selected_block_size"] = None
        meta["detect_mode_used"] = ""
        meta["det_confidence"] = 0.0
        meta["decode_attempt_total"] = 0
        meta["fallback_hits"] = 0
        meta["protocol_path_used"] = protocol_path_used

        locator_debug: Dict[str, Any] = {}
        meta["control_plane_kinds"] = (
            [] if control_plane_kinds is None else list(control_plane_kinds)
        )
        meta["control_session"] = (
            None if control_session is None else dict(control_session)
        )
        meta["control_layout"] = (
            None if control_layout is None else dict(control_layout)
        )
        meta["control_generation"] = (
            None if control_generation is None else dict(control_generation)
        )
        meta["control_generations_seen"] = (
            []
            if control_generations_seen is None
            else [int(v) for v in control_generations_seen]
        )
        meta["decoded_plane"] = "unknown"
        meta["decoded_control_family"] = ""
        meta["decoded_control_kind"] = ""

        # Decode control plane
        if decoded_chunk_id is not None:
            meta["decoded_chunk_id"] = int(decoded_chunk_id)
            control_kind = control_kind_from_wire_chunk_id(decoded_chunk_id)
            if control_kind is not None:
                meta["decoded_plane"] = "control"
                meta["decoded_control_family"] = control_family_for_kind(control_kind)
                meta["decoded_control_kind"] = control_kind
                try:
                    if decoded_payload is not None and control_kind == "session":
                        meta["decoded_control_payload"] = decode_session_bootstrap(
                            decoded_payload
                        )
                    elif decoded_payload is not None and control_kind == "layout":
                        meta["decoded_control_payload"] = decode_layout_bootstrap(
                            decoded_payload
                        )
                    elif decoded_payload is not None and control_kind == "generation":
                        meta["decoded_control_payload"] = decode_generation_control(
                            decoded_payload
                        )
                except Exception:
                    meta["decoded_control_payload"] = {
                        "decode_error": "control_payload_parse_failed"
                    }
            elif int(decoded_chunk_id) > 0:
                meta["decoded_plane"] = "data"

        # Apply v31 metadata
        if v31_meta is not None:
            self.metadata_builder.apply_v31_meta_to_debug(
                meta=meta, v31_meta=v31_meta, protocol=protocol
            )
            locator_debug = (
                v31_meta if isinstance(v31_meta, dict) else {}  # type: ignore[assignment]
            )

        # Protocol-specific probes
        if layered_failure_trace is not None:
            meta["layered_control_trace"] = dict(layered_failure_trace)
        elif protocol_path_used == "basic":
            locator_debug = probe_locator_debug(
                meta=meta,
                frame=frame,
                track_roi_local=track_roi_local,
                forced_roi_local=forced_roi_local,
                grid_w=grid_w,
                grid_h=grid_h,
                locator_confidence_threshold=locator_confidence_threshold,
            )
        elif protocol_path_used == "compact":
            locator_debug = probe_compact_debug(
                meta=meta,
                frame=frame,
                track_roi_local=track_roi_local,
                forced_roi_local=forced_roi_local,
            )

        # Legacy locator fields
        if not manual_strict:
            meta["locator_bbox_projection"] = None
            meta["locator_confidence_projection"] = 0.0
            meta["locator_bbox_cc"] = None
            meta["locator_confidence_cc"] = 0.0
        else:
            meta["locator_bbox_projection"] = None
            meta["locator_confidence_projection"] = 0.0
            meta["locator_bbox_cc"] = None
            meta["locator_confidence_cc"] = 0.0

        # Probe basic detector
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
                    self.drawer.draw_rect(canvas, mapped, (0, 0, 255), thickness=2)
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
                self.drawer.draw_rect(canvas, probe.bbox, (0, 0, 255), thickness=2)
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

        # Draw ROIs
        if forced_roi_local is not None and not manual_strict:
            self.drawer.draw_rect(canvas, forced_roi_local, (0, 255, 255), thickness=3)
            meta["locator_bbox_in_forced_roi"] = None
            meta["locator_confidence_in_forced_roi"] = 0.0
        elif forced_roi_local is not None:
            self.drawer.draw_rect(canvas, forced_roi_local, (0, 255, 255), thickness=3)
            meta["locator_bbox_in_forced_roi"] = None
            meta["locator_confidence_in_forced_roi"] = 0.0

        if track_roi_local is not None:
            self.drawer.draw_rect(canvas, track_roi_local, (255, 255, 0), thickness=2)
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
            self.drawer.draw_rect(canvas, det_bbox_local, (0, 0, 255), thickness=3)
            meta["det_bbox_local"] = [int(v) for v in det_bbox_local]
            det_abs = _roi_local_to_abs(det_bbox_local, capture_region)
            if det_abs is not None:
                meta["det_bbox_abs"] = [int(v) for v in det_abs]

        # Save main snapshot files
        stem = os.path.join(self.debug_dir, f"frame_{frame_index:05d}")
        self.drawer.save_image(stem + ".raw.png", raw)
        self.drawer.save_image(stem + ".annotated.png", canvas)
        self.drawer.save_image(stem + ".png", canvas)

        import json

        with open(stem + ".json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        self.metadata_builder.record_debug_indexes(
            debug_dir=self.debug_dir, frame_index=frame_index, meta=meta
        )

        # Protocol-standard debug artifact set
        frame_dir = os.path.join(self.debug_dir, f"frame_{frame_index:05d}")
        os.makedirs(frame_dir, exist_ok=True)
        self.drawer.save_image(os.path.join(frame_dir, "frame_raw.png"), raw)

        # Finder candidates overlay
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
                        self.drawer.draw_rect(
                            finder_canvas, bbox_tuple, (0, 0, 255), thickness=2  # type: ignore[arg-type]
                        )
        self.drawer.save_image(
            os.path.join(frame_dir, "finder_candidates.png"), finder_canvas
        )

        # Quad overlay
        quad_canvas = raw.copy()
        if isinstance(locator_debug, dict):
            quad_src = locator_debug.get("quad_src")
            if isinstance(quad_src, list) and len(quad_src) == 4:
                try:
                    q = tuple((float(p[0]), float(p[1])) for p in quad_src)
                    if len(q) == 4:
                        self.drawer.draw_quad(
                            quad_canvas, q, (0, 255, 0), thickness=2  # type: ignore[arg-type]
                        )
                except Exception:
                    pass
        self.drawer.save_image(os.path.join(frame_dir, "quad_selected.png"), quad_canvas)

        # Bbox crop
        crop_rect = det_bbox_local
        if crop_rect is None:
            probe_bbox = meta.get("v31_probe_bbox")
            if isinstance(probe_bbox, list) and len(probe_bbox) == 4:
                crop_rect = tuple(int(v) for v in probe_bbox)  # type: ignore[assignment]
        if crop_rect is None:
            finder_candidates = (
                locator_debug.get("finder_candidates")
                if isinstance(locator_debug, dict)
                else None
            )
            if isinstance(finder_candidates, list) and finder_candidates:
                first = finder_candidates[0]
                if isinstance(first, dict):
                    bbox = first.get("bbox")
                    if isinstance(bbox, list) and len(bbox) == 4:
                        crop_rect = tuple(int(v) for v in bbox)  # type: ignore[assignment]
        if crop_rect is not None:
            x, y, w, h = crop_rect
            x1 = max(0, x)
            y1 = max(0, y)
            x2 = min(raw.shape[1], x + w)
            y2 = min(raw.shape[0], y + h)
            if x1 < x2 and y1 < y2:
                self.drawer.save_image(
                    os.path.join(frame_dir, "bbox_crop.png"), raw[y1:y2, x1:x2].copy()
                )

        # Warp and grid overlays
        warp = (
            getattr(v31_meta, "locator_warped_preview", None)
            if v31_meta is not None
            else None
        )
        if warp is not None and isinstance(warp, np.ndarray):
            warp_img = warp.copy()
            self.drawer.save_image(os.path.join(frame_dir, "warp.png"), warp_img)
            grid_overlay = warp_img.copy()
            sample_overlay = warp_img.copy()
            if isinstance(locator_debug, dict):
                grid_bbox = locator_debug.get("grid_bbox_std")
                if isinstance(grid_bbox, list) and len(grid_bbox) == 4:
                    gx, gy, gw, gh = [int(v) for v in grid_bbox]
                    self.drawer.draw_rect(
                        grid_overlay, (gx, gy, gw, gh), (255, 0, 0), thickness=2
                    )
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
                                self.drawer.draw_rect(
                                    sample_overlay,
                                    (px - 1, py - 1, 3, 3),
                                    (0, 255, 255),
                                    thickness=1,
                                )
                    except Exception:
                        pass
            self.drawer.save_image(os.path.join(frame_dir, "grid_overlay.png"), grid_overlay)
            self.drawer.save_image(
                os.path.join(frame_dir, "sample_points.png"), sample_overlay
            )
        else:
            self.drawer.save_image(os.path.join(frame_dir, "warp.png"), raw)
            self.drawer.save_image(os.path.join(frame_dir, "grid_overlay.png"), raw)
            self.drawer.save_image(os.path.join(frame_dir, "sample_points.png"), raw)
