from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from screen_airdrop.receiver.locator.state_machine import GeometryState, GeometryStateMachine


@dataclass
class _FakeLocateResult:
    quad_src: np.ndarray
    homography: np.ndarray
    homography_inv: np.ndarray
    grid_bbox_std: tuple[int, int, int, int]
    warped: np.ndarray

    @dataclass
    class _Quality:
        confidence: float
        warp_rmse: float

    quality: _Quality
    locator_engine: str = "fake"


class _FakeLocator:
    def __init__(self, results):
        self._results = list(results)
        self._roi = None

    def locate(self, frame):
        del frame
        return self._results.pop(0)

    def get_current_roi(self):
        return self._roi

    def update_roi_from_bbox(self, bbox):
        self._roi = bbox

    def reset_roi(self):
        self._roi = None


def _geometry_from_locate(loc, generation: int) -> GeometryState:
    return GeometryState(
        stream_id="test:0",
        geometry_generation=generation,
        quad_src=np.array(loc.quad_src, copy=True),
        homography=np.array(loc.homography, copy=True),
        homography_inv=np.array(loc.homography_inv, copy=True),
        source_capture_index=0,
        last_success_frame_id=0,
        last_success_chunk_id=0,
        quality_score=float(loc.quality.confidence),
        lock_mode="tracking",
        grid_bbox_std=(
            int(loc.grid_bbox_std[0]),
            int(loc.grid_bbox_std[1]),
            int(loc.grid_bbox_std[2]),
            int(loc.grid_bbox_std[3]),
        ),
        warped_shape=(int(loc.warped.shape[1]), int(loc.warped.shape[0])),
        locator_engine=str(loc.locator_engine),
        det_confidence=float(loc.quality.confidence),
        homography_rmse=float(loc.quality.warp_rmse),
    )

def _loc(confidence: float = 0.9, rmse: float = 1.0):
    return _FakeLocateResult(
        quad_src=np.zeros((4, 2), dtype=np.float32),
        homography=np.eye(3, dtype=np.float32),
        homography_inv=np.eye(3, dtype=np.float32),
        grid_bbox_std=(1, 2, 3, 4),
        warped=np.zeros((100, 100, 3), dtype=np.uint8),
        quality=_FakeLocateResult._Quality(confidence=confidence, warp_rmse=rmse),
    )


def test_geometry_state_machine_locks_after_first_success():
    machine = GeometryStateMachine(
        locator=_FakeLocator([_loc()]),
        locate_to_geometry=_geometry_from_locate,
    )
    frame = np.zeros((10, 10, 3), dtype=np.uint8)

    decision = machine.submit_frame(frame, 0, force_reacquire=True)
    assert decision.candidate_geometry is not None
    accepted = machine.propose_update(
        proposed_geometry=decision.candidate_geometry,
        decode_quality=0.9,
        used_geometry_generation=machine.current_generation,
    )
    assert accepted is True
    machine.record_success(
        geometry=decision.candidate_geometry,
        bbox=(0, 0, 10, 10),
        decode_mode="reacquire_locator",
    )

    assert machine.lock_mode == "locked"
    assert machine.current_geometry is not None
    assert machine.current_geometry.lock_mode == "locked"


def test_geometry_state_machine_keeps_locked_geometry_until_failure_threshold():
    machine = GeometryStateMachine(
        locator=_FakeLocator([_loc(), _loc()]),
        locate_to_geometry=_geometry_from_locate,
    )
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    decision = machine.submit_frame(frame, 0, force_reacquire=True)
    machine.propose_update(
        proposed_geometry=decision.candidate_geometry,
        decode_quality=0.9,
        used_geometry_generation=machine.current_generation,
    )
    machine.record_success(
        geometry=decision.candidate_geometry,
        bbox=(0, 0, 10, 10),
        decode_mode="reacquire_locator",
    )
    assert machine.lock_mode == "locked"
    decision = machine.submit_frame(frame, 10)
    assert decision.reuse_first is True
    assert decision.accepted_geometry is not None
    assert decision.candidate_geometry is None
    assert machine.lock_mode == "locked"


def test_geometry_state_machine_only_unlocks_after_consecutive_reuse_failures():
    machine = GeometryStateMachine(locator=_FakeLocator([]), lock_fail_reacquire_threshold=5)
    geometry = GeometryState(
        stream_id="test:0",
        geometry_generation=1,
        quad_src=np.zeros((4, 2), dtype=np.float32),
        homography=np.eye(3, dtype=np.float32),
        homography_inv=np.eye(3, dtype=np.float32),
        source_capture_index=0,
        last_success_frame_id=0,
        last_success_chunk_id=0,
        quality_score=0.9,
        lock_mode="locked",
    )
    machine.propose_update(
        proposed_geometry=geometry,
        decode_quality=0.9,
        used_geometry_generation=machine.current_generation,
    )
    machine.record_success(geometry=geometry, decode_mode="reacquire_locator")

    for _ in range(4):
        assert machine.record_failure(decode_mode="geometry_reuse") is False
        assert machine.current_geometry is not None

    assert machine.lock_mode == "locked"
    assert machine.record_failure(decode_mode="geometry_reuse") is True
    assert machine.lock_mode == "acquire"
    assert machine.current_geometry is None
