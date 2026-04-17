"""Common scheduling-layer package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.common.scheduling.interfaces import (
        GenerationUnitCandidate,
        ScheduledUnit,
        SchedulerContext,
        TransmissionSchedule,
        UnitScheduler,
    )
    from screen_airdrop.common.scheduling.policies import OgrbPolicy

__all__ = [
    "GenerationUnitCandidate",
    "OgrbPolicy",
    "SchedulerContext",
    "ScheduledUnit",
    "TransmissionSchedule",
    "UnitScheduler",
]


def __getattr__(name):
    if name == "OgrbPolicy":
        from screen_airdrop.common.scheduling.policies import OgrbPolicy

        return OgrbPolicy
    if name in {
        "GenerationUnitCandidate",
        "SchedulerContext",
        "ScheduledUnit",
        "TransmissionSchedule",
        "UnitScheduler",
    }:
        from screen_airdrop.common.scheduling import interfaces as _interfaces

        return getattr(_interfaces, name)
    raise AttributeError(name)
