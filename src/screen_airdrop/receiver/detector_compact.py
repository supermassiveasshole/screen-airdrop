# pyright: reportArgumentType=false, reportCallIssue=false
"""Compact protocol (7×7 finder) detector.

This module provides specialized detection for compact protocol's 7×7 finder patterns.
Unlike the basic protocol's 9×9 finders, 7×7 finders are smaller and require different
detection parameters and validation strategies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np


@dataclass
class QuadDetectResult:
    """Result of quad detection."""

    quad: np.ndarray  # 4×2 array of corner coordinates (TL, TR, BR, BL)
    confidence: float  # 0.0-1.0


_FINDER7_TEMPLATE = np.array(
    [
        [1, 1, 1, 1, 1, 1, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 1, 1, 1, 1, 1, 1],
    ],
    dtype=np.float32,
)


def _finder_patch_score(gray: np.ndarray, x: int, y: int, size: int) -> float:
    patch = gray[y : y + size, x : x + size]
    if patch.shape[0] != size or patch.shape[1] != size:
        return -1.0
    if patch.mean() <= 1.0 or patch.mean() >= 254.0:
        return -1.0
    small = cv2.resize(patch, (7, 7), interpolation=cv2.INTER_AREA).astype(np.float32)
    small = 1.0 - (small / 255.0)  # black -> 1, white -> 0
    # Template agreement plus a small contrast bonus.
    mse = float(np.mean((small - _FINDER7_TEMPLATE) ** 2))
    contrast = float(np.std(patch) / 128.0)
    return max(0.0, 1.0 - mse) + min(0.5, contrast)


def _corner_search_windows(view_shape: Tuple[int, int]) -> List[Tuple[str, Tuple[int, int, int, int]]]:
    h, w = view_shape
    wx = max(56, int(w * 0.15))
    wy = max(56, int(h * 0.18))
    return [
        ("tl", (0, 0, wx, wy)),
        ("tr", (max(0, w - wx), 0, wx, wy)),
        ("br", (max(0, w - wx), max(0, h - wy), wx, wy)),
        ("bl", (0, max(0, h - wy), wx, wy)),
    ]


def _detect_7x7_inner_cores(view: np.ndarray) -> List[Tuple[float, float, float]]:
    """Detect finder centers from the stable 3x3 black inner cores.

    In real screen captures the inner 3x3 core is often much cleaner than the full
    7x7 contour because timing rails and outer borders interfere with contour trees.
    We search each corner window independently and look for a dark, nearly-square
    connected component with a bright ring around it.
    """
    gray = view.mean(axis=2).astype(np.uint8)
    h, w = gray.shape
    found: List[Tuple[float, float, float]] = []

    for _name, (x0, y0, ww, hh) in _corner_search_windows((h, w)):
        x1 = min(w, x0 + ww)
        y1 = min(h, y0 + hh)
        roi = gray[y0:y1, x0:x1]
        if roi.size == 0:
            continue

        thr_candidates = []
        otsu_thr, _ = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        thr_candidates.extend([int(otsu_thr), 96, 112, 128])

        best_score = -1.0
        best: Optional[Tuple[float, float, float]] = None
        for thr in thr_candidates:
            bin_img = ((roi < thr).astype(np.uint8) * 255)
            num, _labels, stats, cents = cv2.connectedComponentsWithStats(bin_img, 8)
            for i in range(1, num):
                x, y, bw, bh, area = [int(v) for v in stats[i]]
                if area < 40 or area > 2500:
                    continue
                if bw < 8 or bh < 8:
                    continue
                ratio = max(bw, bh) / max(1.0, min(bw, bh))
                if ratio > 1.35:
                    continue
                if x <= 0 or y <= 0 or x + bw >= roi.shape[1] or y + bh >= roi.shape[0]:
                    continue

                cx, cy = [float(v) for v in cents[i]]

                # Validate bright ring around the dark core.
                pad = max(2, int(round(max(bw, bh) * 0.45)))
                rx0 = max(0, x - pad)
                ry0 = max(0, y - pad)
                rx1 = min(roi.shape[1], x + bw + pad)
                ry1 = min(roi.shape[0], y + bh + pad)
                outer = roi[ry0:ry1, rx0:rx1]
                if outer.size == 0:
                    continue
                mask = np.zeros_like(outer, dtype=np.uint8)
                mask[y - ry0 : y - ry0 + bh, x - rx0 : x - rx0 + bw] = 1
                ring = outer[mask == 0]
                core = roi[y : y + bh, x : x + bw]
                if ring.size == 0 or core.size == 0:
                    continue
                core_mean = float(np.mean(core))
                ring_mean = float(np.mean(ring))
                if ring_mean <= core_mean + 25.0:
                    continue

                size = float(max(bw, bh) * (7.0 / 3.0))
                score = (ring_mean - core_mean) / 255.0
                score += min(0.5, float(area) / 500.0)
                if score > best_score:
                    best_score = score
                    best = (x0 + cx, y0 + cy, size)

        if best is not None:
            found.append(best)
    return found


def _detect_7x7_finders_corner_template(view: np.ndarray) -> List[Tuple[float, float, float]]:
    """Search each corner window for a 7x7 finder using template scoring.

    This path is tuned for manual-ROI / screen-capture use where the symbol already occupies
    most of the frame and the four finders should be near the image corners.
    """
    gray = view.mean(axis=2).astype(np.uint8)
    h, w = gray.shape
    base = max(3.0, min(w / 184.0, h / 120.0))
    scales = sorted({max(12, int(round(7.0 * base * m))) for m in (0.7, 0.85, 1.0, 1.15, 1.3)})
    found: List[Tuple[float, float, float]] = []

    for name, (x0, y0, ww, hh) in _corner_search_windows((h, w)):
        best_score = -1.0
        best: Optional[Tuple[float, float, float]] = None
        x1 = min(w, x0 + ww)
        y1 = min(h, y0 + hh)
        for size in scales:
            step = max(2, size // 5)
            max_x = x1 - size
            max_y = y1 - size
            if max_x < x0 or max_y < y0:
                continue
            for y in range(y0, max_y + 1, step):
                for x in range(x0, max_x + 1, step):
                    score = _finder_patch_score(gray, x, y, size)
                    if score < 0.0:
                        continue
                    cx = x + (size / 2.0)
                    cy = y + (size / 2.0)
                    if name == "tl":
                        ref_x, ref_y = 0.0, 0.0
                    elif name == "tr":
                        ref_x, ref_y = float(w - 1), 0.0
                    elif name == "br":
                        ref_x, ref_y = float(w - 1), float(h - 1)
                    else:
                        ref_x, ref_y = 0.0, float(h - 1)
                    dist = np.hypot(cx - ref_x, cy - ref_y)
                    dist_norm = dist / max(1.0, np.hypot(ww, hh))
                    score -= 0.55 * float(dist_norm)
                    if score > best_score:
                        best_score = score
                        best = (cx, cy, float(size))
        if best is not None and best_score >= 0.72:
            found.append(best)
    return found


def _detect_7x7_finders_hybrid(view: np.ndarray) -> List[Tuple[float, float, float]]:
    """Detect 7×7 compact finders using hybrid approach.

    Strategy:
    1. Multi-threshold contour detection with relaxed constraints
    2. Feature validation using center (black) + ring (white) sampling
    3. Returns list of (cx, cy, size) tuples

    Args:
        view: BGR image to search

    Returns:
        List of (center_x, center_y, size) for detected finders
    """
    gray = view.mean(axis=2).astype(np.uint8)
    all_candidates = []

    # Phase 1: Multi-threshold contour detection with relaxed constraints
    for thr_val in [100, 128, 150]:
        _, binary = cv2.threshold(gray, thr_val, 255, cv2.THRESH_BINARY)
        contours, hierarchy = cv2.findContours(binary, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        if hierarchy is None:
            continue

        h = hierarchy[0]
        for i, c in enumerate(contours):
            area = cv2.contourArea(c)

            # Relaxed area constraints for 7×7 (smaller than 9×9)
            # At 3px/module: 7×7 = 21×21 = 441px²
            # At 15px/module: 7×7 = 105×105 = 11025px²
            if area < 200 or area > 12000:
                continue

            # Require at least 1 level of nesting (relaxed from 2)
            child = int(h[i][2])
            if child < 0:
                continue

            # Shape validation
            rect = cv2.minAreaRect(c)
            (cx, cy), (w, h_rect), _ = rect

            if w < 10 or h_rect < 10:
                continue

            # Relaxed aspect ratio for 7×7
            ratio = max(w, h_rect) / max(1.0, min(w, h_rect))
            if ratio > 1.4:
                continue

            size = (w + h_rect) / 2
            all_candidates.append((float(cx), float(cy), float(size)))

    if not all_candidates:
        return []

    # Phase 2: Feature validation using relative contrast
    verified = []
    for cx, cy, size in all_candidates:
        # Estimate module size (7×7 finder)
        module_size = size / 7.0

        # Sample center region (3×3 black core)
        center_samples = []
        for dy in [-0.5, 0, 0.5]:
            for dx in [-0.5, 0, 0.5]:
                px = int(cx + dx * module_size)
                py = int(cy + dy * module_size)
                if 0 <= py < gray.shape[0] and 0 <= px < gray.shape[1]:
                    center_samples.append(int(gray[py, px]))

        if not center_samples:
            continue

        center_mean = np.mean(center_samples)

        # Sample white ring (at ~2 modules from center)
        ring_samples = []
        for angle_deg in [0, 45, 90, 135, 180, 225, 270, 315]:
            angle_rad = np.deg2rad(angle_deg)
            dist = 2.0 * module_size
            px = int(cx + dist * np.cos(angle_rad))
            py = int(cy + dist * np.sin(angle_rad))
            if 0 <= py < gray.shape[0] and 0 <= px < gray.shape[1]:
                ring_samples.append(int(gray[py, px]))

        if not ring_samples:
            continue

        ring_mean = np.mean(ring_samples)

        # Relative contrast validation (not fixed thresholds)
        contrast = abs(ring_mean - center_mean)
        if contrast < 40:  # Minimum contrast requirement
            continue

        # Center should be darker than ring
        if center_mean >= ring_mean:
            continue

        # Additional validation: check if center is dark enough relative to image
        if center_mean > 160:  # Too bright to be a black center
            continue

        verified.append((cx, cy, size))

    # Phase 3: Deduplication
    if not verified:
        return []

    final = []
    for cx, cy, size in verified:
        is_dup = False
        for fx, fy, _ in final:
            dist = np.sqrt((cx - fx) ** 2 + (cy - fy) ** 2)
            if dist < 15:
                is_dup = True
                break
        if not is_dup:
            final.append((cx, cy, size))

    return final


def _pick_compact_corners(
    candidates: List[Tuple[float, float, float]], view_shape: Tuple[int, int]
) -> Optional[np.ndarray]:
    """Select 4 corners from finder candidates with position priors.

    Args:
        candidates: List of (cx, cy, size) tuples
        view_shape: (height, width) of the view

    Returns:
        4×2 array of [TL, TR, BR, BL] corners, or None if invalid
    """
    if len(candidates) < 4:
        return None

    h, w = view_shape
    pts = np.array([(cx, cy) for cx, cy, _ in candidates], dtype=np.float32)

    # Select corners using sum/diff strategy (like basic)
    sums = pts[:, 0] + pts[:, 1]
    diffs = pts[:, 0] - pts[:, 1]

    tl_idx = np.argmin(sums)
    br_idx = np.argmax(sums)
    tr_idx = np.argmax(diffs)
    bl_idx = np.argmin(diffs)

    indices = {tl_idx, tr_idx, br_idx, bl_idx}
    if len(indices) < 4:
        return None

    quad = np.array(
        [pts[tl_idx], pts[tr_idx], pts[br_idx], pts[bl_idx]], dtype=np.float32
    )

    # Geometric validation with position priors
    # 1. Check if corners are reasonably spaced
    top_width = float(np.linalg.norm(quad[1] - quad[0]))
    bottom_width = float(np.linalg.norm(quad[2] - quad[3]))
    left_height = float(np.linalg.norm(quad[3] - quad[0]))
    right_height = float(np.linalg.norm(quad[2] - quad[1]))

    if min(top_width, bottom_width, left_height, right_height) < 30:
        return None

    # 2. Check aspect ratio consistency
    width_ratio = max(top_width, bottom_width) / max(1.0, min(top_width, bottom_width))
    height_ratio = max(left_height, right_height) / max(1.0, min(left_height, right_height))

    if width_ratio > 1.8 or height_ratio > 1.8:
        return None

    # 3. Check overall aspect ratio (should match layout: ~160/96 ≈ 1.67)
    avg_width = (top_width + bottom_width) / 2
    avg_height = (left_height + right_height) / 2
    aspect_ratio = avg_width / max(1.0, avg_height)

    # Allow 1.2 to 2.5 range (covers 160/96 ≈ 1.67)
    if aspect_ratio < 1.0 or aspect_ratio > 3.0:
        return None

    # 4. Position priors: corners should be near frame edges
    # TL should be in upper-left quadrant
    if quad[0, 0] > w * 0.6 or quad[0, 1] > h * 0.6:
        return None

    # BR should be in lower-right quadrant
    if quad[2, 0] < w * 0.4 or quad[2, 1] < h * 0.4:
        return None

    return quad


def detect_symbol_quad_compact(view: np.ndarray) -> Optional[QuadDetectResult]:
    """Detect compact protocol symbol quad using 7×7 finder detection.

    This is the main entry point for compact protocol quad detection.
    Uses corner-first strategy optimized for 7×7 finders.

    Args:
        view: BGR image to search (local ROI)

    Returns:
        QuadDetectResult with quad and confidence, or None if detection fails
    """
    # First try the stable inner-core detector.
    candidates = _detect_7x7_inner_cores(view)

    # Then try corner-local template search. It is better aligned with compact's
    # real use case: the symbol usually fills most of the ROI and the four finders
    # remain near the corners even when borders are cropped.
    if len(candidates) < 4:
        candidates = _detect_7x7_finders_corner_template(view)
    if len(candidates) < 4:
        candidates = _detect_7x7_finders_hybrid(view)

    if len(candidates) < 4:
        return None

    # Select 4 corners with position priors
    quad = _pick_compact_corners(candidates, view.shape[:2])

    if quad is None:
        return None

    # Calculate confidence based on number of candidates and geometry
    # More candidates = higher confidence (up to a point)
    candidate_score = min(1.0, len(candidates) / 6.0)

    # Geometry score based on quad regularity
    top_width = float(np.linalg.norm(quad[1] - quad[0]))
    bottom_width = float(np.linalg.norm(quad[2] - quad[3]))
    left_height = float(np.linalg.norm(quad[3] - quad[0]))
    right_height = float(np.linalg.norm(quad[2] - quad[1]))

    width_consistency = 1.0 - abs(top_width - bottom_width) / max(top_width, bottom_width)
    height_consistency = 1.0 - abs(left_height - right_height) / max(left_height, right_height)
    geometry_score = (width_consistency + height_consistency) / 2.0

    # Combined confidence
    confidence = 0.6 * candidate_score + 0.4 * geometry_score
    confidence = float(np.clip(confidence, 0.0, 1.0))

    return QuadDetectResult(quad=quad, confidence=confidence)
