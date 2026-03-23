"""ROI utilities for screen-airdrop receiver."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.receiver.roi.manager import RoiManager
    from screen_airdrop.receiver.roi.policy import RoiPolicy
    from screen_airdrop.receiver.roi.profile import load_profile, save_profile
    from screen_airdrop.receiver.roi.selector import select_region
    from screen_airdrop.receiver.roi.setup import setup_roi
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
    "RoiPolicy",
    "setup_roi",
    "select_region",
    "load_profile",
    "save_profile",
]


def __getattr__(name):
    if name == "RoiManager":
        from screen_airdrop.receiver.roi.manager import RoiManager

        return RoiManager
    if name == "RoiPolicy":
        from screen_airdrop.receiver.roi.policy import RoiPolicy

        return RoiPolicy
    if name in {"load_profile", "save_profile"}:
        from screen_airdrop.receiver.roi import profile as _profile

        return getattr(_profile, name)
    if name == "select_region":
        from screen_airdrop.receiver.roi.selector import select_region

        return select_region
    if name == "setup_roi":
        from screen_airdrop.receiver.roi.setup import setup_roi

        return setup_roi
    if name in {
        "build_track_roi_from_bbox",
        "ensure_roi_valid",
        "expand_roi_local",
        "roi_abs_to_local",
        "roi_local_to_abs",
    }:
        from screen_airdrop.receiver.roi import transforms as _transforms

        return getattr(_transforms, name)
    raise AttributeError(name)
