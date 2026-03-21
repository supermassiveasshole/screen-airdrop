"""Protocol-specific debug probes."""

from typing import Any, Dict, Optional, Tuple

import numpy as np

from screen_airdrop.receiver.detector_basic import (
    _bbox_from_non_black,
    detect_symbol_bbox,
)
from screen_airdrop.receiver.locator.basic import (
    LocateError,
    LocatorConfig,
    locate_frame,
)


def probe_locator_debug(
    meta: Dict[str, Any],
    frame: np.ndarray,
    track_roi_local: Optional[Tuple[int, int, int, int]],
    forced_roi_local: Optional[Tuple[int, int, int, int]],
    grid_w: int,
    grid_h: int,
    locator_confidence_threshold: float,
) -> Dict[str, Any]:
    """Probe locator for debug information.

    Args:
        meta: Metadata dict to populate
        frame: Input frame
        track_roi_local: Tracking ROI
        forced_roi_local: Forced ROI
        grid_w: Grid width
        grid_h: Grid height
        locator_confidence_threshold: Confidence threshold

    Returns:
        Debug artifacts dict
    """
    probe_roi = track_roi_local if track_roi_local is not None else forced_roi_local
    loc_cfg = LocatorConfig(
        grid_w=int(grid_w),
        grid_h=int(grid_h),
        confidence_threshold=float(locator_confidence_threshold),
    )
    loc = locate_frame(frame=frame, search_roi=probe_roi, config=loc_cfg)
    if isinstance(loc, LocateError):
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


def probe_compact_debug(
    meta: Dict[str, Any],
    frame: np.ndarray,
    track_roi_local: Optional[Tuple[int, int, int, int]],
    forced_roi_local: Optional[Tuple[int, int, int, int]],
) -> Dict[str, Any]:
    """Probe compact protocol for debug information.

    Args:
        meta: Metadata dict to populate
        frame: Input frame
        track_roi_local: Tracking ROI
        forced_roi_local: Forced ROI

    Returns:
        Debug artifacts dict
    """

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
                meta["finder_candidates"] = [
                    {"bbox": [int(v) for v in mapped], "score": 0.85}
                ]
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
