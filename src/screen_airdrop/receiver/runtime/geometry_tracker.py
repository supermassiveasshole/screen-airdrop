"""Backward-compatible runtime geometry tracker wrapper."""

from screen_airdrop.receiver.locator.state_machine import (
    GeometryDecision,
    GeometryState,
    GeometryStateSnapshot,
    LiveGeometryStateMachine,
)

GeometryTracker = LiveGeometryStateMachine

__all__ = [
    "GeometryDecision",
    "GeometryState",
    "LiveGeometryStateMachine",
    "GeometryStateSnapshot",
    "GeometryTracker",
]
