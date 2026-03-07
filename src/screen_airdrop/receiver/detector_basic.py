"""Basic protocol detector: finder-pattern and bbox detection."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np


@dataclass
class QuadDetectResult:
    quad: np.ndarray  # (4,2) ordered tl,tr,br,bl
    confidence: float


@dataclass
class BboxDetectResult:
    bbox: Tuple[int, int, int, int]
    confidence: float


def _threshold_candidates(gray: np.ndarray) -> List[np.ndarray]:
    outs = []
    _, b1 = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    outs.append(b1)
    b2 = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 3)
    outs.append(b2)
    return outs


def _finder_candidates(bin_img: np.ndarray) -> List[Tuple[float, float, float]]:
    # returns list of (cx, cy, size)
    contours, hierarchy = cv2.findContours(bin_img, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return []
    h = hierarchy[0]
    out = []
    for i, c in enumerate(contours):
        area = cv2.contourArea(c)
        if area < 80:
            continue
        # Nested hierarchy: contour -> child -> grandchild.
        child = int(h[i][2])
        if child < 0:
            continue
        grand = int(h[child][2])
        if grand < 0:
            continue
        peri = cv2.arcLength(c, True)
        if peri <= 0:
            continue
        approx = cv2.approxPolyDP(c, 0.05 * peri, True)
        if len(approx) != 4:
            continue
        rect = cv2.minAreaRect(c)
        (cx, cy), (w, hh), _ = rect
        if w < 4 or hh < 4:
            continue
        ratio = max(w, hh) / max(1.0, min(w, hh))
        if ratio > 1.35:
            continue
        out.append((float(cx), float(cy), float(max(w, hh))))
    # dedupe close points
    dedup = []
    for cx, cy, s in sorted(out, key=lambda t: -t[2]):
        keep = True
        for ox, oy, os in dedup:
            if (cx - ox) ** 2 + (cy - oy) ** 2 < (0.35 * min(s, os)) ** 2:
                keep = False
                break
        if keep:
            dedup.append((cx, cy, s))
    return dedup[:12]


def _score_quad(pts: np.ndarray) -> float:
    # prefer large convex quadrilateral.
    hull = cv2.convexHull(pts.astype(np.float32))
    area = cv2.contourArea(hull)
    if area <= 0:
        return -1.0
    rect = cv2.minAreaRect(pts.astype(np.float32))
    (_, _), (w, h), _ = rect
    if w <= 0 or h <= 0:
        return -1.0
    ratio = max(w, h) / max(1.0, min(w, h))
    return float(area) - 300.0 * abs(ratio - (16.0 / 9.0))


def _pick_corners_fast(cands: List[Tuple[float, float, float]]) -> Optional[np.ndarray]:
    """Fast corner selection using spatial extrema."""
    if len(cands) < 4:
        return None
    max_size = max(s for _, _, s in cands)
    filtered = [(x, y, s) for x, y, s in cands if s >= max_size * 0.5]
    if len(filtered) < 4:
        return None
    pts = np.array([[x, y] for x, y, _ in filtered], dtype=np.float32)
    sums = pts[:, 0] + pts[:, 1]
    diffs = pts[:, 0] - pts[:, 1]
    tl = pts[np.argmin(sums)]
    br = pts[np.argmax(sums)]
    tr = pts[np.argmax(diffs)]
    bl = pts[np.argmin(diffs)]
    return np.array([tl, tr, br, bl], dtype=np.float32)


def detect_symbol_quad(frame: np.ndarray) -> Optional[QuadDetectResult]:
    gray = frame.mean(axis=2).astype(np.uint8)
    best = None
    best_score = -1e18
    for b in _threshold_candidates(gray):
        cands = _finder_candidates(b)
        if len(cands) < 4:
            continue
        # Fast path: try spatial extrema first
        quad = _pick_corners_fast(cands)
        if quad is not None:
            top = float(np.linalg.norm(quad[1] - quad[0]))
            bottom = float(np.linalg.norm(quad[2] - quad[3]))
            left = float(np.linalg.norm(quad[3] - quad[0]))
            right = float(np.linalg.norm(quad[2] - quad[1]))
            if min(top, bottom, left, right) >= 20.0:
                if max(top, bottom) / max(1.0, min(top, bottom)) <= 1.7:
                    if max(left, right) / max(1.0, min(left, right)) <= 1.7:
                        ar = (top + bottom) / max(1.0, (left + right))
                        if 1.2 <= ar <= 2.8:
                            score = _score_quad(quad)
                            if score > best_score:
                                best_score = score
                                best = quad
        # Fallback: exhaustive search on top 8 candidates
        if best is None and len(cands) > 4:
            top_cands = sorted(cands, key=lambda t: -t[2])[:8]
            for combo in itertools.combinations(top_cands, 4):
                pts = np.array([[x, y] for x, y, _ in combo], dtype=np.float32)
                sizes = np.array([s for _, _, s in combo], dtype=np.float32)
                sratio = float(np.max(sizes)) / float(max(1.0, np.min(sizes)))
                if sratio > 2.2:
                    continue

                sums = pts[:, 0] + pts[:, 1]
                diffs = pts[:, 0] - pts[:, 1]
                tl = pts[np.argmin(sums)]
                br = pts[np.argmax(sums)]
                tr = pts[np.argmax(diffs)]
                bl = pts[np.argmin(diffs)]
                quad = np.array([tl, tr, br, bl], dtype=np.float32)

                top = float(np.linalg.norm(tr - tl))
                bottom = float(np.linalg.norm(br - bl))
                left = float(np.linalg.norm(bl - tl))
                right = float(np.linalg.norm(br - tr))
                if min(top, bottom, left, right) < 20.0:
                    continue
                if max(top, bottom) / max(1.0, min(top, bottom)) > 1.7:
                    continue
                if max(left, right) / max(1.0, min(left, right)) > 1.7:
                    continue
                ar = (top + bottom) / max(1.0, (left + right))
                if ar < 1.2 or ar > 2.8:
                    continue

                score = _score_quad(quad) - (sratio - 1.0) * 500.0
                if score > best_score:
                    best_score = score
                    best = quad
    if best is None:
        return None
    conf = max(0.0, min(1.0, best_score / 50000.0))
    return QuadDetectResult(quad=best, confidence=conf)


# ============================================================================
# Bbox detection (higher-level)
# ============================================================================

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
    touches = (
        int(x <= 1) + int(y <= 1) + int((x + bw) >= frame_w - 1) + int((y + bh) >= frame_h - 1)
    )
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


def detect_symbol_bbox(frame: np.ndarray) -> Optional[BboxDetectResult]:
    """Detect symbol bounding box using simplified heuristics."""
    h, w = frame.shape[:2]
    candidates = []

    # Try dark window detection first
    dark_window = _detect_dark_window(frame)
    if dark_window is not None:
        wx, wy, ww, wh = dark_window
        view = frame[wy : wy + wh, wx : wx + ww]

        # Try quad detection in dark window
        quad = detect_symbol_quad(view)
        if quad is not None:
            qbox = _bbox_from_quad(quad.quad, frame_w=ww, frame_h=wh)
            gbox = _clamp_bbox((wx + qbox[0], wy + qbox[1], qbox[2], qbox[3]), w, h)
            px = max(4, int(gbox[2] * 0.02))
            py = max(4, int(gbox[3] * 0.02))
            gbox = _clamp_bbox(
                (gbox[0] - px, gbox[1] - py, gbox[2] + 2 * px, gbox[3] + 2 * py), w, h
            )
            if _bbox_quality_ok(gbox, w, h):
                qconf = max(0.72, float(quad.confidence))
                candidates.append((gbox, qconf))

    # Fallback to full-frame quad detection
    if not candidates:
        quad = detect_symbol_quad(frame)
        if quad is not None:
            qbox = _bbox_from_quad(quad.quad, frame_w=w, frame_h=h)
            px = max(4, int(qbox[2] * 0.02))
            py = max(4, int(qbox[3] * 0.02))
            qbox = _clamp_bbox(
                (qbox[0] - px, qbox[1] - py, qbox[2] + 2 * px, qbox[3] + 2 * py), w, h
            )
            if _bbox_quality_ok(qbox, w, h):
                qconf = max(0.6, float(quad.confidence))
                candidates.append((qbox, qconf))

    if candidates:
        best_bbox, best_conf = max(candidates, key=lambda it: _bbox_score(it[0], it[1]))
        return BboxDetectResult(bbox=best_bbox, confidence=float(best_conf))

    # Final fallback: non-black bbox
    bbox = _bbox_from_non_black(frame)
    if bbox is not None:
        return BboxDetectResult(bbox=bbox, confidence=0.35)

    return None
