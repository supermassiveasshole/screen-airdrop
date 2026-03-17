"""Geometry tracker: lock/reacquire state machine for geometry reuse."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Tuple

import numpy as np

if TYPE_CHECKING:
    from screen_airdrop.receiver.frame_locator import FrameLocator
    from screen_airdrop.receiver.locator_basic import LocateError, LocateResult


@dataclass(frozen=True)
class GeometryState:
    """Immutable geometry state with homography matrix."""

    stream_id: str
    geometry_generation: int
    quad_src: Optional[np.ndarray]
    homography: Optional[np.ndarray]
    homography_inv: Optional[np.ndarray]
    source_capture_index: int
    last_success_frame_id: int
    last_success_chunk_id: int
    quality_score: float
    lock_mode: str
    grid_bbox_std: Tuple[int, int, int, int] = (0, 0, 0, 0)
    warped_shape: Tuple[int, int] = (0, 0)
    locator_engine: str = "geometry_reuse"
    det_confidence: float = 0.0
    homography_rmse: float = 0.0


class GeometryTracker:
    """Manages geometry state machine: acquire → locked → reacquire."""

    def __init__(
        self,
        *,
        locator: "FrameLocator",
        locator_confidence_threshold: float = 0.55,
        lock_fail_reacquire_threshold: int = 5,
    ):
        """Initialize geometry tracker.

        Args:
            locator: FrameLocator instance for ROI tracking
            locator_confidence_threshold: Minimum quality score to accept geometry
            lock_fail_reacquire_threshold: Consecutive failures before reacquire
        """
        self._locator = locator
        self._locator_confidence_threshold = locator_confidence_threshold
        self._lock_fail_reacquire_threshold = lock_fail_reacquire_threshold

        self._geometry_state: Optional[GeometryState] = None
        self._geometry_generation = 0
        self._geometry_fail_streak = 0
        self._lock_mode = "acquire"
        self._locked_geometry_age = 0

    @property
    def current_geometry(self) -> Optional[GeometryState]:
        """Get current geometry state."""
        return self._geometry_state

    @property
    def current_generation(self) -> int:
        """Get current geometry generation."""
        return self._geometry_generation

    @property
    def lock_mode(self) -> str:
        """Get current lock mode: 'acquire' or 'locked'."""
        return self._lock_mode

    @property
    def fail_streak(self) -> int:
        """Get current failure streak."""
        return self._geometry_fail_streak

    def propose_update(
        self,
        *,
        proposed_geometry: Optional[GeometryState],
        decode_quality: float,
        used_geometry_generation: int,
    ) -> bool:
        """Propose geometry update from decode result.

        Args:
            proposed_geometry: Proposed geometry state from decoder
            decode_quality: Quality score of decode
            used_geometry_generation: Generation used for decode

        Returns:
            True if geometry was updated, False otherwise
        """
        if proposed_geometry is None:
            return False

        if decode_quality < self._locator_confidence_threshold:
            return False

        if used_geometry_generation != self._geometry_generation:
            return False

        # Accept geometry and lock
        self._geometry_generation += 1
        self._lock_mode = "locked"
        self._geometry_state = GeometryState(
            **{
                **proposed_geometry.__dict__,
                "geometry_generation": self._geometry_generation,
                "lock_mode": "locked",
            }
        )
        self._locked_geometry_age = 0

        return True

    def record_success(
        self,
        *,
        geometry: Optional[GeometryState] = None,
        bbox: Optional[Tuple[int, int, int, int]] = None,
    ) -> None:
        """Record successful decode, reset failure streak.

        Args:
            geometry: Optional geometry state (for propose_update compatibility)
            bbox: Optional detection bbox for ROI update
        """
        self._geometry_fail_streak = 0
        if self._lock_mode == "locked":
            self._locked_geometry_age += 1

        # Update ROI tracking if bbox provided
        if bbox is not None:
            self._locator.update_roi_from_bbox(bbox)

    def record_failure(self) -> bool:
        """Record failed decode, increment failure streak.

        Returns:
            True if should reacquire (exceeded threshold), False otherwise
        """
        self._geometry_fail_streak += 1

        if self._geometry_fail_streak >= self._lock_fail_reacquire_threshold and self._lock_mode == "locked":
            # Reacquire: reset to acquire mode
            self._lock_mode = "acquire"
            self._geometry_state = None
            self._geometry_generation += 1
            self._geometry_fail_streak = 0
            self._locked_geometry_age = 0
            return True

        return False

    def should_reacquire(self) -> bool:
        """Check if should reacquire geometry (in acquire mode)."""
        return self._lock_mode == "acquire"

    def force_reacquire(self) -> None:
        """Force reacquire by resetting to acquire mode."""
        self._lock_mode = "acquire"
        self._geometry_state = None
        self._geometry_generation += 1
        self._geometry_fail_streak = 0
        self._locked_geometry_age = 0

    def get_locked_geometry_age(self) -> int:
        """Get age of locked geometry (frames since lock)."""
        return self._locked_geometry_age

    def get_current_roi(self) -> Optional[Tuple[int, int, int, int]]:
        """Get current tracking ROI from locator.

        Returns:
            Current ROI (x, y, w, h) or None
        """
        return self._locator.get_current_roi()

    def locate_frame(self, frame: np.ndarray) -> "LocateResult | LocateError":
        """Run locator (only in acquire mode).

        Args:
            frame: Input frame

        Returns:
            LocateResult on success, LocateError on failure

        Raises:
            RuntimeError: If called in locked mode
        """
        if self._lock_mode != "acquire":
            raise RuntimeError("Cannot locate in locked mode")
        return self._locator.locate(frame)

