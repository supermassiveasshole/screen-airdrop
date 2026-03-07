"""V3.1 detector: stable bbox extraction for symbol region."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np

from screen_airdrop.receiver.detector_v3 import detect_symbol_quad
from screen_airdrop.receiver.locator import calibrate_threshold, detect_locator_bbox


@dataclass
class DetectResultV31:
    bbox: Tuple[int, int, int, int]
    confidence: float


EXPECTED_AR = 160.0 / 96.0


def _clamp_bbox(bbox: Tuple[int, int, int, int], w: int, h: int) -> Tuple[int, int, int, int]:
    x, y, bw, bh = bbox
    x = max(0, int(x))
    y = max(0, int(y))
    bw = max(1, int(bw))
    bh = max(1, int(bh))
    if x + bw > w:
        bw = max(1, w - x)
    if y + bh > h:
        bh = max(1, h - y)
    return x, y, bw, bh


def _bbox_from_quad(quad: np.ndarray, frame_w: int, frame_h: int) -> Tuple[int, int, int, int]:
    x1 = int(np.floor(float(np.min(quad[:, 0]))))
    y1 = int(np.floor(float(np.min(quad[:, 1]))))
    x2 = int(np.ceil(float(np.max(quad[:, 0]))))
    y2 = int(np.ceil(float(np.max(quad[:, 1]))))
    return _clamp_bbox((x1, y1, x2 - x1, y2 - y1), frame_w, frame_h)


def _bbox_quality_ok(bbox: Tuple[int, int, int, int], frame_w: int, frame_h: int) -> bool:
    x, y, bw, bh = bbox
    if bw < 64 or bh < 64:
        return False
    area_ratio = float(bw * bh) / float(max(1, frame_w * frame_h))
    # Track-mode crops can legitimately occupy most of the local view.
    if area_ratio > 0.985:
        return False
    ar = float(max(bw, bh)) / float(max(1, min(bw, bh)))
    if ar < 1.1 or ar > 3.5:
        return False
    # Must not touch all four borders simultaneously.
    touches = int(x <= 1) + int(y <= 1) + int((x + bw) >= frame_w - 1) + int((y + bh) >= frame_h - 1)
    if touches >= 4:
        return False
    return True


def _bbox_score(bbox: Tuple[int, int, int, int], confidence: float) -> float:
    _, _, bw, bh = bbox
    ar = float(max(1, bw)) / float(max(1, bh))
    ar_penalty = abs(ar - EXPECTED_AR)
    return float(confidence) - (ar_penalty * 0.8)


def _detect_dark_window(frame: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    gray = frame.mean(axis=2).astype(np.uint8)
    # Sender window has a large dark canvas.
    dark = (gray < 40).astype(np.uint8) * 255
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((5, 5), dtype=np.uint8), iterations=1)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    h, w = gray.shape
    frame_area = float(max(1, h * w))
    best = None
    best_score = -1.0
    for i in range(1, n):
        x = int(stats[i, cv2.CC_STAT_LEFT])
        y = int(stats[i, cv2.CC_STAT_TOP])
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        area = float(stats[i, cv2.CC_STAT_AREA])
        if bw < 120 or bh < 120:
            continue
        area_ratio = area / frame_area
        if area_ratio < 0.08:
            continue
        touches = int(x <= 1) + int(y <= 1) + int((x + bw) >= w - 1) + int((y + bh) >= h - 1)
        # Ignore full-screen dark background.
        if touches >= 4:
            continue
        rect_area = float(max(1, bw * bh))
        fill = area / rect_area
        ar = float(max(1, bw)) / float(max(1, bh))
        if ar < 1.0 or ar > 3.2:
            continue
        score = area_ratio + (fill * 0.35) - (abs(ar - EXPECTED_AR) * 0.18)
        if score > best_score:
            best_score = score
            best = (x, y, bw, bh)
    return best


def _bbox_from_non_black(frame: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    gray = frame.mean(axis=2).astype(np.uint8)
    ys, xs = np.where(gray > 8)
    if len(xs) == 0:
        return None
    x1 = int(np.min(xs))
    x2 = int(np.max(xs))
    y1 = int(np.min(ys))
    y2 = int(np.max(ys))
    if x2 - x1 < 64 or y2 - y1 < 64:
        return None
    h, w = gray.shape
    touches_left = x1 <= 1
    touches_top = y1 <= 1
    touches_right = x2 >= w - 2
    touches_bottom = y2 >= h - 2
    # Reject complete full-screen mask.
    if touches_left and touches_top and touches_right and touches_bottom:
        return None
    bbox = (x1, y1, (x2 - x1 + 1), (y2 - y1 + 1))
    if not _bbox_quality_ok(bbox, w, h):
        return None
    return bbox


def detect_symbol_bbox_v31(frame: np.ndarray) -> Optional[DetectResultV31]:
    h, w = frame.shape[:2]
    candidates = []

    # Fast path: try projection locator first (much faster than quad detection)
    thr = calibrate_threshold(frame, mode="auto")
    loc = detect_locator_bbox(frame, threshold=thr, use_projection=True)
    if loc is not None:
        pbox = _clamp_bbox(loc.bbox, w, h)
        if _bbox_quality_ok(pbox, w, h):
            pconf = max(0.7, float(loc.confidence))
            candidates.append((pbox, pconf))

    # Only try expensive quad detection if projection failed
    if not candidates:
        dark_window = _detect_dark_window(frame)
        if dark_window is not None:
            wx, wy, ww, wh = dark_window
            view = frame[wy : wy + wh, wx : wx + ww]

            # Try projection in dark window first
            loc = detect_locator_bbox(view, threshold=thr, use_projection=True)
            if loc is not None:
                pbox = _clamp_bbox(loc.bbox, ww, wh)
                gbox = _clamp_bbox((wx + pbox[0], wy + pbox[1], pbox[2], pbox[3]), w, h)
                if _bbox_quality_ok(gbox, w, h):
                    pconf = max(0.72, float(loc.confidence))
                    candidates.append((gbox, pconf))

    # Fallback to quad detection only if all else fails
    if not candidates:
        quad = detect_symbol_quad(frame)
        if quad is not None:
            qbox = _bbox_from_quad(quad.quad, frame_w=w, frame_h=h)
            px = max(4, int(qbox[2] * 0.02))
            py = max(4, int(qbox[3] * 0.02))
            qbox = _clamp_bbox((qbox[0] - px, qbox[1] - py, qbox[2] + 2 * px, qbox[3] + 2 * py), w, h)
            if _bbox_quality_ok(qbox, w, h):
                qconf = max(0.6, float(quad.confidence))
                candidates.append((qbox, qconf))

    if candidates:
        best_bbox, best_conf = max(candidates, key=lambda it: _bbox_score(it[0], it[1]))
        return DetectResultV31(bbox=best_bbox, confidence=float(best_conf))

    bbox = _bbox_from_non_black(frame)
    if bbox is not None:
        # Weak heuristic fallback: keep confidence conservative to avoid
        # over-trusting non-black envelopes on busy desktops.
        return DetectResultV31(bbox=bbox, confidence=0.35)

    return None
