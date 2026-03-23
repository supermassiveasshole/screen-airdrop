"""Common scheduling-layer package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.common.scheduling.interfaces import (
        ScheduledUnit,
        TransmissionSchedule,
        UnitScheduler,
    )

__all__ = [
    "ScheduledUnit",
    "TransmissionSchedule",
    "UnitScheduler",
]


def __getattr__(name):
    if name in __all__:
        from screen_airdrop.common.scheduling import interfaces as _interfaces

        return getattr(_interfaces, name)
    raise AttributeError(name)
