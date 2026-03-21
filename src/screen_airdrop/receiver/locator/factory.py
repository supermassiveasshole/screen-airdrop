"""Reusable locator assembly for live and replay decode paths."""

from __future__ import annotations

from typing import Optional, Tuple

from screen_airdrop.receiver.locator.basic import LocateError, locate_frame, locate_frame_legacy
from screen_airdrop.receiver.locator.frame_locator import FrameLocator


def auto_locator_with_fallback(frame, search_roi, config=None):
    """Precise locator with legacy fallback on failure or weak confidence."""
    result = locate_frame(frame, search_roi, config)
    if isinstance(result, LocateError) or result.quality.confidence < 0.55:
        result = locate_frame_legacy(frame, search_roi, config)
        if hasattr(result, "quad_src") and not hasattr(result, "locator_engine"):
            setattr(result, "locator_engine", "legacy")
        return result
    if hasattr(result, "quad_src") and not hasattr(result, "locator_engine"):
        setattr(result, "locator_engine", "auto")
    return result


def build_frame_locator(
    *,
    grid_w: int,
    grid_h: int,
    guard_band: int,
    corner_size: int,
    initial_roi: Optional[Tuple[int, int, int, int]] = None,
    manual_mode: bool = False,
) -> FrameLocator:
    """Create the repository-standard stateful frame locator."""
    locator_func = locate_frame_legacy if manual_mode else auto_locator_with_fallback
    return FrameLocator(
        locator_func=locator_func,
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=guard_band,
        corner_size=corner_size,
        initial_roi=initial_roi,
        fixed_roi=manual_mode,
    )


class ProtocolGeometryLocator:
    """Protocol-aware locator wrapper used only for replay diagnostics/stateful replay."""

    def __init__(self, decoder):
        self._decoder = decoder

    def locate(self, frame):
        return self._decoder.locate_geometry(
            frame=frame,
            detect_mode="full",
            forced_roi=None,
        )

    def get_current_roi(self):
        return None

    def update_roi_from_bbox(self, bbox):
        del bbox

    def reset_roi(self):
        return None


def build_protocol_geometry_locator(decoder) -> ProtocolGeometryLocator:
    """Build a replay-only protocol-aware locator wrapper."""
    return ProtocolGeometryLocator(decoder)
