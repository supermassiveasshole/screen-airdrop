"""Geometry tracker: lock/reacquire state machine for geometry reuse."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np


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
        locator_confidence_threshold: float = 0.55,
        lock_fail_reacquire_threshold: int = 5,
    ):
        """Initialize geometry tracker.

        Args:
            locator_confidence_threshold: Minimum quality score to accept geometry
            lock_fail_reacquire_threshold: Consecutive failures before reacquire
        """
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

    def record_success(self) -> None:
        """Record successful decode, reset failure streak."""
        self._geometry_fail_streak = 0
        if self._lock_mode == "locked":
            self._locked_geometry_age += 1

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
