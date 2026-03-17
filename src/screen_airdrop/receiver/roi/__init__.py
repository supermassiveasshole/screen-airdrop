"""ROI utilities for screen-airdrop receiver."""

from screen_airdrop.receiver.roi.manager import RoiManager
from screen_airdrop.receiver.roi.transforms import (
    build_track_roi_from_bbox,
    ensure_roi_valid,
    expand_roi_local,
    roi_abs_to_local,
    roi_local_to_abs,
)

__all__ = [
    "RoiManager",
    "ensure_roi_valid",
    "roi_abs_to_local",
    "roi_local_to_abs",
    "expand_roi_local",
    "build_track_roi_from_bbox",
]
