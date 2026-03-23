"""Shared scheduling-layer interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from screen_airdrop.common.information import TransmissionUnit


@dataclass(frozen=True)
class ScheduledUnit:
    """One scheduled transmission opportunity."""

    unit: TransmissionUnit
    transport_epoch_id: int
    realization_index: int = 0
    realization_count: int = 1


@dataclass(frozen=True)
class TransmissionSchedule:
    """Ordered schedule of transmission opportunities."""

    units: Sequence[ScheduledUnit]


class UnitScheduler(object):
    """Scheduling-layer interface over information units."""

    def schedule_units(
        self,
        units: Sequence[TransmissionUnit],
        *,
        transport_epoch_id: int,
        realization_count: int = 1,
    ) -> TransmissionSchedule:
        raise NotImplementedError

