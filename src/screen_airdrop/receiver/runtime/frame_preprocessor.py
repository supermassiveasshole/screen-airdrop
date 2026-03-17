"""Frame preprocessing: fingerprinting and deduplication."""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

_FINGERPRINT_H = 16
_FINGERPRINT_W = 24
_PREP_ROI_FRACTION = 0.8
_DEDUP_THRESHOLD = 0.015


def compute_fingerprint(frame: np.ndarray, roi: Optional[Tuple[int, int, int, int]] = None) -> bytes:
    """Compute perceptual hash fingerprint for deduplication.

    Args:
        frame: BGR frame (H, W, 3)
        roi: Optional (x, y, w, h) region of interest

    Returns:
        Fingerprint bytes (grayscale downsampled to 16x24)
    """
    if roi is not None:
        x, y, w, h = roi
        frame = frame[y : y + h, x : x + w]

    h, w = frame.shape[:2]
    ys = np.linspace(0, max(0, h - 1), _FINGERPRINT_H, dtype=np.int32)
    xs = np.linspace(0, max(0, w - 1), _FINGERPRINT_W, dtype=np.int32)
    sample = frame[np.ix_(ys, xs)].astype(np.uint16, copy=False)

    # Convert BGR to grayscale: 0.114*B + 0.587*G + 0.299*R
    b = sample[:, :, 0]
    g = sample[:, :, 1]
    r = sample[:, :, 2]
    gray = ((29 * b + 150 * g + 77 * r) >> 8).astype(np.uint8)

    return gray.tobytes()


def fingerprint_diff(curr: bytes, prev: Optional[bytes]) -> float:
    """Compute normalized difference between two fingerprints.

    Args:
        curr: Current fingerprint
        prev: Previous fingerprint (None if first frame)

    Returns:
        Normalized difference in [0.0, 1.0]
    """
    if prev is None:
        return 1.0

    curr_arr = np.frombuffer(curr, dtype=np.uint8)
    prev_arr = np.frombuffer(prev, dtype=np.uint8)

    if curr_arr.shape != prev_arr.shape:
        return 1.0

    return float(np.abs(curr_arr.astype(np.int16) - prev_arr.astype(np.int16)).mean()) / 255.0


def is_duplicate(curr: bytes, prev: Optional[bytes], threshold: float = _DEDUP_THRESHOLD) -> bool:
    """Check if current frame is a duplicate of previous frame.

    Args:
        curr: Current fingerprint
        prev: Previous fingerprint
        threshold: Similarity threshold (default 0.015)

    Returns:
        True if frames are similar enough to be considered duplicates
    """
    return fingerprint_diff(curr, prev) < threshold


def clip_roi_to_frame(
    roi: Optional[Tuple[int, int, int, int]],
    *,
    frame_width: int,
    frame_height: int,
) -> Tuple[int, int, int, int]:
    """Clip ROI to frame bounds, or compute default centered ROI.

    Args:
        roi: Optional (x, y, w, h) region of interest
        frame_width: Frame width
        frame_height: Frame height

    Returns:
        Clipped (x, y, w, h) tuple
    """
    if roi is None:
        # Default: centered ROI at 80% of frame size
        crop_w = max(64, min(frame_width, int(round(frame_width * _PREP_ROI_FRACTION))))
        crop_h = max(64, min(frame_height, int(round(frame_height * _PREP_ROI_FRACTION))))
        crop_w = min(crop_w, frame_width)
        crop_h = min(crop_h, frame_height)
        x = max(0, (frame_width - crop_w) // 2)
        y = max(0, (frame_height - crop_h) // 2)
        return x, y, crop_w, crop_h

    # Clip provided ROI to frame bounds
    x, y, w, h = roi
    x = max(0, min(int(x), max(0, frame_width - 1)))
    y = max(0, min(int(y), max(0, frame_height - 1)))
    w = max(1, min(int(w), frame_width - x))
    h = max(1, min(int(h), frame_height - y))
    return x, y, w, h
