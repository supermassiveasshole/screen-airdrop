"""Stateful frame locator with ROI tracking."""

from typing import Callable, Optional, Tuple

import numpy as np

from screen_airdrop.receiver.locator_basic import LocateError, LocateResult, LocatorConfig

# 定位算法回调类型 (新签名：使用 LocatorConfig)
LocatorFunc = Callable[
    [np.ndarray, Optional[Tuple[int, int, int, int]], Optional[LocatorConfig]],
    LocateResult | LocateError,
]


class FrameLocator:
    """Stateful frame locator with ROI tracking.

    Responsibilities:
    - ROI tracking: dynamic updates (auto mode) vs fixed ROI (manual mode)
    - Locator algorithm decoupling: injected via callback
    - Pure locator orchestration (no geometry state management)
    """

    def __init__(
        self,
        *,
        locator_func: LocatorFunc,
        grid_w: int,
        grid_h: int,
        guard_band: int,
        corner_size: int,
        initial_roi: Optional[Tuple[int, int, int, int]] = None,
        fixed_roi: bool = False,
    ):
        """Initialize frame locator.

        Args:
            locator_func: Locator algorithm callback
            grid_w: Grid width
            grid_h: Grid height
            guard_band: Guard band size
            corner_size: Corner marker size
            initial_roi: Initial search ROI (x, y, w, h)
            fixed_roi: If True, ROI is fixed (manual mode)
        """
        self._locator_func = locator_func
        self._grid_w = grid_w
        self._guard_band = guard_band
        self._corner_size = corner_size
        self._initial_roi = initial_roi
        self._track_roi = initial_roi
        self._fixed_roi = fixed_roi

        # Create LocatorConfig for this locator
        self._config = LocatorConfig(
            grid_w=grid_w,
            grid_h=grid_h,
            guard_band=guard_band,
            corner_size=corner_size,
        )

    def locate(self, frame: np.ndarray) -> LocateResult | LocateError:
        """Run locator with current ROI tracking state.

        Args:
            frame: Input frame

        Returns:
            LocateResult on success, LocateError on failure
        """
        search_roi = self._track_roi or self._initial_roi

        return self._locator_func(frame, search_roi, self._config)

    def update_roi_from_bbox(self, bbox: Tuple[int, int, int, int]) -> None:
        """Update tracking ROI from successful detection bbox.

        Args:
            bbox: Detection bounding box (x, y, w, h)
        """
        if self._fixed_roi:
            # Manual mode: fixed ROI, no updates
            return

        # Auto mode: dynamic ROI tracking with 10% margin
        bx, by, bw, bh = bbox
        margin = max(24, min(96, int(min(bw, bh) * 0.10)))
        x1 = max(0, bx - margin)
        y1 = max(0, by - margin)
        self._track_roi = (x1, y1, bw + 2 * margin, bh + 2 * margin)

    def get_current_roi(self) -> Optional[Tuple[int, int, int, int]]:
        """Get current tracking ROI.

        Returns:
            Current ROI (x, y, w, h) or None
        """
        return self._track_roi or self._initial_roi

    def reset_roi(self) -> None:
        """Reset to initial ROI."""
        self._track_roi = self._initial_roi


