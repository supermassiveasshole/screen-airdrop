"""ROI coordinate transformation utilities."""

from typing import Optional, Tuple


def ensure_roi_valid(roi: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    """Ensure ROI is valid (minimum 128x128).

    Args:
        roi: ROI tuple (x, y, w, h)

    Returns:
        Validated ROI tuple

    Raises:
        ValueError: If ROI is too small
    """
    x, y, w, h = roi
    if w < 128 or h < 128:
        raise ValueError("roi too small; minimum is 128x128")
    return int(x), int(y), int(w), int(h)


def roi_abs_to_local(
    roi_abs: Optional[Tuple[int, int, int, int]],
    capture_region: Optional[Tuple[int, int, int, int]],
    frame_shape: Tuple[int, int, int],
) -> Optional[Tuple[int, int, int, int]]:
    """Convert absolute ROI coordinates to local frame coordinates.

    Args:
        roi_abs: ROI in absolute screen coordinates (x, y, w, h)
        capture_region: Capture region (x, y, w, h)
        frame_shape: Frame shape (h, w, c)

    Returns:
        ROI in local frame coordinates, or None if invalid
    """
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


def roi_local_to_abs(
    roi_local: Optional[Tuple[int, int, int, int]],
    capture_region: Optional[Tuple[int, int, int, int]],
) -> Optional[Tuple[int, int, int, int]]:
    """Convert local frame ROI coordinates to absolute screen coordinates.

    Args:
        roi_local: ROI in local frame coordinates (x, y, w, h)
        capture_region: Capture region (x, y, w, h)

    Returns:
        ROI in absolute screen coordinates, or None if invalid
    """
    if roi_local is None:
        return None
    if capture_region is None:
        return roi_local
    x, y, w, h = roi_local
    cx, cy, _, _ = capture_region
    return (int(cx + x), int(cy + y), int(w), int(h))


def expand_roi_local(
    roi_local: Optional[Tuple[int, int, int, int]],
    frame_shape: Tuple[int, int, int],
    pad_px: int,
) -> Optional[Tuple[int, int, int, int]]:
    """Expand ROI by padding pixels on all sides.

    Args:
        roi_local: ROI in local frame coordinates (x, y, w, h)
        frame_shape: Frame shape (h, w, c)
        pad_px: Padding in pixels

    Returns:
        Expanded ROI, or None if invalid
    """
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


def build_track_roi_from_bbox(
    det_bbox: Tuple[int, int, int, int],
    frame_shape: Tuple[int, int, int],
    base_margin_px: int,
) -> Tuple[int, int, int, int]:
    """Build tracking ROI from detected bounding box.

    Args:
        det_bbox: Detected bounding box (x, y, w, h)
        frame_shape: Frame shape (h, w, c)
        base_margin_px: Base margin in pixels

    Returns:
        Tracking ROI (x, y, w, h)
    """
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
