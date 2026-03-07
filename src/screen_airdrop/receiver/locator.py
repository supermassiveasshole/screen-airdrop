"""Locator and threshold helpers for V2 auto-ROI decode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np


@dataclass
class LocatorResult:
    bbox: Tuple[int, int, int, int]
    confidence: float


def _find_bands(ratios: np.ndarray, threshold: float, min_len: int) -> list:
    idx = np.where(ratios >= threshold)[0]
    if idx.size == 0:
        return []
    bands = []
    start = int(idx[0])
    prev = int(idx[0])
    for raw in idx[1:]:
        cur = int(raw)
        if cur == prev + 1:
            prev = cur
            continue
        if prev - start + 1 >= min_len:
            bands.append((start, prev))
        start = cur
        prev = cur
    if prev - start + 1 >= min_len:
        bands.append((start, prev))
    return bands


def _detect_locator_bbox_projection(frame: np.ndarray, threshold: int) -> Optional[LocatorResult]:
    gray = frame.mean(axis=2).astype(np.uint8)
    mask = (gray > threshold).astype(np.uint8)
    h, w = mask.shape
    if h <= 0 or w <= 0:
        return None

    row_ratios = mask.mean(axis=1)
    col_ratios = mask.mean(axis=0)
    row_bands = _find_bands(row_ratios, threshold=0.85, min_len=2)
    col_bands = _find_bands(col_ratios, threshold=0.85, min_len=2)
    if len(row_bands) < 2 or len(col_bands) < 2:
        return None

    def _band_penalty(band: Tuple[int, int], size: int, axis: str) -> float:
        start, end = band
        thickness = end - start + 1
        p = 0.0
        # Bands touching capture boundaries are likely UI chrome, not locator border.
        if start <= 1 or end >= size - 2:
            p += 0.35
        # Overly thick bands are usually not locator borders.
        if thickness > max(2, int(0.06 * size)):
            p += 0.20
        # Horizontal bands very close to top menu/title are suspicious.
        if axis == "row" and start < int(0.05 * size):
            p += 0.20
        return p

    # Optimize: pick outermost bands instead of O(n^4) search
    if not row_bands or not col_bands:
        return None

    # Pick first and last row bands (top and bottom borders)
    top = row_bands[0]
    bottom = row_bands[-1]
    if bottom[0] <= top[1] or bottom[0] - top[1] < int(0.3 * h):
        return None

    # Pick first and last col bands (left and right borders)
    left = col_bands[0]
    right = col_bands[-1]
    if right[0] <= left[1] or right[0] - left[1] < int(0.3 * w):
        return None

    x = left[0]
    y = top[0]
    ww = right[1] - left[0] + 1
    hh = bottom[1] - top[0] + 1

    if ww <= 0 or hh <= 0:
        return None

    area_ratio = float(ww * hh) / float(w * h)
    if area_ratio < 0.2:
        return None

    edge_strength = float(
        (
            row_ratios[top[0] : top[1] + 1].mean()
            + row_ratios[bottom[0] : bottom[1] + 1].mean()
            + col_ratios[left[0] : left[1] + 1].mean()
            + col_ratios[right[0] : right[1] + 1].mean()
        )
        / 4.0
    )
    penalty = (
        _band_penalty(top, h, "row")
        + _band_penalty(bottom, h, "row")
        + _band_penalty(left, w, "col")
        + _band_penalty(right, w, "col")
    )
    best_score = edge_strength + 0.2 * area_ratio - penalty
    best = (x, y, ww, hh, best_score)

    if best is None:
        return None
    x, y, ww, hh, score = best
    confidence = max(0.0, min(1.0, float(score)))
    return LocatorResult(bbox=(int(x), int(y), int(ww), int(hh)), confidence=confidence)


def calibrate_threshold(frame: np.ndarray, mode: str = "auto", fixed: int = 127) -> int:
    if mode != "auto":
        return int(fixed)

    gray = frame.mean(axis=2).astype(np.uint8)
    hist, _ = np.histogram(gray, bins=256, range=(0, 256))
    total = gray.size
    sum_total = int(np.dot(np.arange(256), hist))

    sum_b = 0.0
    w_b = 0.0
    max_var = -1.0
    threshold = 127

    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b = sum_b / w_b
        m_f = (sum_total - sum_b) / w_f
        var_between = w_b * w_f * (m_b - m_f) ** 2
        if var_between > max_var:
            max_var = var_between
            threshold = t
    return int(threshold)


def _detect_locator_bbox_connected_components(
    frame: np.ndarray, threshold: int, min_area_ratio: float = 0.01
) -> Optional[LocatorResult]:
    try:
        import cv2  # pylint: disable=import-outside-toplevel
    except Exception:
        return None

    gray = frame.mean(axis=2).astype(np.uint8)
    _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)

    nlabels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if nlabels <= 1:
        return None

    h, w = gray.shape[:2]
    frame_area = float(h * w)

    best_idx = -1
    best_score = -1.0
    best_bbox = None

    for idx in range(1, nlabels):
        x = int(stats[idx, cv2.CC_STAT_LEFT])
        y = int(stats[idx, cv2.CC_STAT_TOP])
        ww = int(stats[idx, cv2.CC_STAT_WIDTH])
        hh = int(stats[idx, cv2.CC_STAT_HEIGHT])
        area = float(stats[idx, cv2.CC_STAT_AREA])

        area_ratio = area / frame_area
        if area_ratio < min_area_ratio:
            continue

        bbox_area_ratio = float(ww * hh) / frame_area
        aspect = float(ww) / float(max(1, hh))
        aspect_score = 1.0 - min(1.0, abs(aspect - (16.0 / 9.0)) / (16.0 / 9.0))

        score = 0.55 * area_ratio + 0.35 * bbox_area_ratio + 0.10 * aspect_score
        if score > best_score:
            best_score = score
            best_idx = idx
            best_bbox = (x, y, ww, hh)

    if best_idx < 0 or best_bbox is None:
        return None

    confidence = max(0.0, min(1.0, best_score * 4.0))
    return LocatorResult(bbox=best_bbox, confidence=confidence)


def detect_locator_bbox(
    frame: np.ndarray,
    threshold: int,
    min_area_ratio: float = 0.01,
    use_projection: bool = True,
) -> Optional[LocatorResult]:
    if use_projection:
        projection = _detect_locator_bbox_projection(frame, threshold=threshold)
        if projection is not None:
            return projection
    return _detect_locator_bbox_connected_components(frame, threshold=threshold, min_area_ratio=min_area_ratio)
