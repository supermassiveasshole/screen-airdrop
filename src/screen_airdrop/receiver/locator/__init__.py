"""Locator package exports."""

from screen_airdrop.receiver.locator.basic import (
    LocateError,
    LocateFailReason,
    LocateQuality,
    LocateResult,
    LocatorConfig,
    locate_frame,
    locate_frame_legacy,
)
from screen_airdrop.receiver.locator.diagnostics import GeometryDiagnosticsCollector
from screen_airdrop.receiver.locator.factory import (
    ProtocolGeometryLocator,
    auto_locator_with_fallback,
    build_frame_locator,
    build_protocol_geometry_locator,
)
from screen_airdrop.receiver.locator.frame_locator import FrameLocator
from screen_airdrop.receiver.locator.state_machine import (
    GeometryDecision,
    GeometryState,
    GeometryStateMachine,
    GeometryStateSnapshot,
    GeometryTracker,
    LiveGeometryStateMachine,
)

__all__ = [
    "FrameLocator",
    "GeometryDiagnosticsCollector",
    "GeometryDecision",
    "GeometryState",
    "LiveGeometryStateMachine",
    "GeometryStateMachine",
    "GeometryStateSnapshot",
    "GeometryTracker",
    "LocateError",
    "LocateFailReason",
    "LocateQuality",
    "LocateResult",
    "LocatorConfig",
    "ProtocolGeometryLocator",
    "auto_locator_with_fallback",
    "build_frame_locator",
    "build_protocol_geometry_locator",
    "locate_frame",
    "locate_frame_legacy",
]
