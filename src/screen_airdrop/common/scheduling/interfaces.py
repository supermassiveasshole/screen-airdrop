"""Shared scheduling-layer interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from screen_airdrop.common.information import TransmissionUnit


@dataclass(frozen=True)
class GenerationUnitCandidate:
    """Generation-scoped candidate units for scheduling."""

    generation_id: int
    units: Sequence[TransmissionUnit]


@dataclass(frozen=True)
class SchedulerContext:
    """Optional scheduler context for generation-aware policies."""

    transport_epoch_id: int
    realization_count: int = 1
    policy: Optional[Any] = None


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
        generation_candidates: Optional[Sequence[GenerationUnitCandidate]] = None,
        scheduler_context: Optional[SchedulerContext] = None,
    ) -> TransmissionSchedule:
        raise NotImplementedError
