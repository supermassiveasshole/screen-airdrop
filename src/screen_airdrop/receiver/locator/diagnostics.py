"""Replay/live geometry diagnostics that do not affect state transitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from screen_airdrop.receiver.locator.state_machine import GeometryState

GeometryLocateAdapter = Callable[[Any, int], Optional[GeometryState]]
GeometryProbeAdapter = Callable[[Any, GeometryState], Dict[str, Any]]


@dataclass
class GeometryDiagnosticsCollector:
    """Collect side-band geometry diagnostics without mutating state."""

    candidate_locate_ok: int = 0
    candidate_locate_fail: int = 0
    probe_ok: int = 0
    probe_fail: int = 0
    last_failure: Dict[str, Any] = field(default_factory=dict)
    last_probe: Dict[str, Any] = field(default_factory=dict)

    def inspect_failure(
        self,
        *,
        frame: Any,
        frame_index: int,
        state: str,
        trusted_geometry_age_frames: int,
        locate_result: Optional[Any],
        locate_to_geometry: Optional[GeometryLocateAdapter],
        probe_geometry: Optional[GeometryProbeAdapter],
    ) -> None:
        candidate_geometry: Optional[GeometryState] = None
        probe: Dict[str, Any] = {}
        if locate_result is None or locate_to_geometry is None:
            self.candidate_locate_fail += 1
        else:
            candidate_geometry = locate_to_geometry(locate_result, frame_index)
            if candidate_geometry is None:
                self.candidate_locate_fail += 1
            else:
                self.candidate_locate_ok += 1
                if probe_geometry is not None:
                    probe = dict(probe_geometry(frame, candidate_geometry))
                    if bool(probe.get("bootstrap_ok", False)):
                        self.probe_ok += 1
                    else:
                        self.probe_fail += 1
                    self.last_probe = probe

        self.last_failure = {
            "frame_index": frame_index,
            "state": state,
            "trusted_geometry_age_frames": trusted_geometry_age_frames,
            "candidate_geometry": {
                "available": candidate_geometry is not None,
                "locator_engine": (
                    ""
                    if candidate_geometry is None
                    else str(candidate_geometry.locator_engine)
                ),
                "det_confidence": (
                    0.0
                    if candidate_geometry is None
                    else float(candidate_geometry.det_confidence)
                ),
                "homography_rmse": (
                    0.0
                    if candidate_geometry is None
                    else float(candidate_geometry.homography_rmse)
                ),
            },
            "protocol_geometry_probe": probe,
        }

    def as_dict(self) -> Dict[str, Any]:
        return {
            "geometry_diagnostics": {
                "candidate_locate_ok": self.candidate_locate_ok,
                "candidate_locate_fail": self.candidate_locate_fail,
                "probe_ok": self.probe_ok,
                "probe_fail": self.probe_fail,
                "last_failure": dict(self.last_failure),
            }
        }


__all__ = ["GeometryDiagnosticsCollector"]
