"""V3 finder-pattern detector."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np


@dataclass
class DetectResultV3:
    quad: np.ndarray  # (4,2) ordered tl,tr,br,bl
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


def detect_symbol_quad(frame: np.ndarray) -> Optional[DetectResultV3]:
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
    return DetectResultV3(quad=best, confidence=conf)
