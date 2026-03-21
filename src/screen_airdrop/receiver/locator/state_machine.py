"""Live-equivalent geometry state machine shared by live and replay paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Tuple

import numpy as np

if TYPE_CHECKING:
    from screen_airdrop.receiver.locator.basic import LocateError, LocateResult


GeometryLocateAdapter = Callable[[Any, int], Optional["GeometryState"]]


@dataclass(frozen=True)
class GeometryState:
    """Trusted geometry snapshot shared across runtime workers and replay."""

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
    protocol_geometry: Any = None


@dataclass(frozen=True)
class GeometryDecision:
    """Decision for the next frame decode attempt."""

    state: str
    accepted_geometry: Optional[GeometryState]
    reuse_first: bool
    should_reacquire: bool
    reacquire_attempted: bool
    candidate_geometry: Optional[GeometryState] = None
    search_roi: Optional[Tuple[int, int, int, int]] = None
    trusted_geometry_age_frames: int = 0


@dataclass(frozen=True)
class GeometryStateSnapshot:
    """Report-friendly snapshot of effective live geometry behavior."""

    current_state: str
    current_generation: int
    fail_streak: int
    trusted_geometry_age_frames: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "geometry_state_current": self.current_state,
            "geometry_generation": self.current_generation,
            "geometry_fail_streak": self.fail_streak,
            "trusted_geometry_age_frames": self.trusted_geometry_age_frames,
        }


class LiveGeometryStateMachine:
    """Minimal acquire/locked state machine used by live and replay."""

    def __init__(
        self,
        *,
        locator: Any,
        stream_id: str = "stream:0",
        search_policy: str = "roi_then_expand",
        fixed_roi: Optional[Tuple[int, int, int, int]] = None,
        locate_to_geometry: Optional[GeometryLocateAdapter] = None,
        locator_confidence_threshold: float = 0.55,
        lock_fail_reacquire_threshold: int = 5,
    ):
        if search_policy not in {"full", "roi_only", "roi_then_expand"}:
            raise ValueError(f"invalid search_policy: {search_policy}")
        self._locator = locator
        self._stream_id = stream_id
        self._search_policy = search_policy
        self._fixed_roi = fixed_roi
        self._locate_to_geometry = locate_to_geometry
        self._locator_confidence_threshold = float(locator_confidence_threshold)
        self._lock_fail_reacquire_threshold = int(lock_fail_reacquire_threshold)

        self._geometry_state: Optional[GeometryState] = None
        self._geometry_generation = 0
        self._geometry_fail_streak = 0
        self._lock_mode = "acquire"
        self._locked_geometry_age = 0

    @property
    def current_geometry(self) -> Optional[GeometryState]:
        return self._geometry_state

    @property
    def current_generation(self) -> int:
        return self._geometry_generation

    @property
    def lock_mode(self) -> str:
        return self._lock_mode

    @property
    def fail_streak(self) -> int:
        return self._geometry_fail_streak

    def get_locked_geometry_age(self) -> int:
        return self._locked_geometry_age

    def get_current_roi(self) -> Optional[Tuple[int, int, int, int]]:
        return self._locator.get_current_roi()

    def should_reacquire(self) -> bool:
        return self._lock_mode == "acquire"

    def force_reacquire(self) -> None:
        self._lock_mode = "acquire"
        self._geometry_state = None
        self._geometry_generation += 1
        self._geometry_fail_streak = 0
        self._locked_geometry_age = 0
        self._locator.reset_roi()

    def locate_frame(self, frame: np.ndarray) -> "LocateResult | LocateError":
        if self._lock_mode != "acquire":
            raise RuntimeError("Cannot locate in locked mode")
        return self._locator.locate(frame)

    def submit_frame(
        self,
        frame: np.ndarray,
        frame_index: int,
        roi_hint: Optional[Tuple[int, int, int, int]] = None,
        *,
        force_reacquire: bool = False,
    ) -> GeometryDecision:
        del frame_index
        trusted = self._geometry_state if self._lock_mode == "locked" else None
        search_roi = self._search_roi(roi_hint)

        if trusted is not None and not force_reacquire:
            return GeometryDecision(
                state=self._lock_mode,
                accepted_geometry=trusted,
                reuse_first=True,
                should_reacquire=False,
                reacquire_attempted=False,
                search_roi=search_roi,
                trusted_geometry_age_frames=self._locked_geometry_age,
            )

        candidate_geometry: Optional[GeometryState] = None
        reacquire_attempted = False
        if self._locate_to_geometry is not None:
            reacquire_attempted = True
            locate_result = self._locate_with_policy(frame)
            if locate_result is not None:
                candidate_geometry = self._locate_to_geometry(
                    locate_result, self._geometry_generation + 1
                )

        return GeometryDecision(
            state=self._lock_mode,
            accepted_geometry=trusted,
            reuse_first=False,
            should_reacquire=self._lock_mode == "acquire" or force_reacquire,
            reacquire_attempted=reacquire_attempted,
            candidate_geometry=candidate_geometry,
            search_roi=search_roi,
            trusted_geometry_age_frames=self._locked_geometry_age,
        )

    def propose_update(
        self,
        *,
        proposed_geometry: Optional[GeometryState],
        decode_quality: float,
        used_geometry_generation: int,
        meta: Optional[object] = None,
    ) -> bool:
        del meta
        if proposed_geometry is None:
            return False
        if decode_quality < self._locator_confidence_threshold:
            return False
        if used_geometry_generation != self._geometry_generation:
            return False

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
        decode_mode: str = "",
        used_reuse_fallback: bool = False,
    ) -> None:
        del geometry, decode_mode, used_reuse_fallback
        self._geometry_fail_streak = 0
        if self._lock_mode == "locked":
            self._locked_geometry_age += 1
        if bbox is not None:
            self._locator.update_roi_from_bbox(bbox)

    def record_failure(
        self,
        *,
        decode_mode: str = "",
        failure_class: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        del decode_mode, failure_class, context
        self._geometry_fail_streak += 1
        if (
            self._lock_mode == "locked"
            and self._geometry_fail_streak >= self._lock_fail_reacquire_threshold
        ):
            self._lock_mode = "acquire"
            self._geometry_state = None
            self._geometry_generation += 1
            self._geometry_fail_streak = 0
            self._locked_geometry_age = 0
            return True
        return False

    def snapshot(self) -> GeometryStateSnapshot:
        return GeometryStateSnapshot(
            current_state=self._lock_mode,
            current_generation=self._geometry_generation,
            fail_streak=self._geometry_fail_streak,
            trusted_geometry_age_frames=self._locked_geometry_age,
        )

    def _search_roi(
        self,
        roi_hint: Optional[Tuple[int, int, int, int]],
    ) -> Optional[Tuple[int, int, int, int]]:
        if self._fixed_roi is not None:
            return self._fixed_roi
        if self._search_policy == "full":
            return None
        return roi_hint or self._locator.get_current_roi()

    def _locate_with_policy(self, frame: np.ndarray) -> Optional[Any]:
        result = self._locator.locate(frame)
        if not hasattr(result, "quad_src"):
            if (
                self._search_policy == "roi_then_expand"
                and self._locator.get_current_roi() is not None
            ):
                self._locator.reset_roi()
                retry = self._locator.locate(frame)
                if hasattr(retry, "quad_src"):
                    return retry
            return None
        return result


GeometryStateMachine = LiveGeometryStateMachine
GeometryTracker = LiveGeometryStateMachine

__all__ = [
    "GeometryDecision",
    "GeometryState",
    "GeometryStateMachine",
    "GeometryStateSnapshot",
    "GeometryTracker",
    "LiveGeometryStateMachine",
]
