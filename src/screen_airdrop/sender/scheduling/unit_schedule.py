"""Sender-side systematic and coded unit scheduling helpers."""

from __future__ import annotations

from typing import List, Optional, Sequence

from screen_airdrop.common.information import TransmissionUnit
from screen_airdrop.common.scheduling import (
    GenerationUnitCandidate,
    ScheduledUnit,
    SchedulerContext,
    TransmissionSchedule,
    UnitScheduler,
)


class BroadcastUnitScheduler(UnitScheduler):
    """Default systematic-only broadcast scheduler."""

    def schedule_units(
        self,
        units: Sequence[TransmissionUnit],
        *,
        transport_epoch_id: int,
        realization_count: int = 1,
        generation_candidates: Optional[Sequence[GenerationUnitCandidate]] = None,
        scheduler_context: Optional[SchedulerContext] = None,
    ) -> TransmissionSchedule:
        scheduled: List[ScheduledUnit] = []
        if generation_candidates:
            flattened_units = []
            for candidate in generation_candidates:
                flattened_units.extend(candidate.units)
            units = flattened_units
        if scheduler_context is not None:
            transport_epoch_id = int(scheduler_context.transport_epoch_id)
            realization_count = int(scheduler_context.realization_count)
        count = max(1, int(realization_count))
        for unit in units:
            for realization_index in range(count):
                scheduled.append(
                    ScheduledUnit(
                        unit=unit,
                        transport_epoch_id=int(transport_epoch_id),
                        realization_index=realization_index,
                        realization_count=count,
                    )
                )
        return TransmissionSchedule(units=scheduled)


class CodedAugmentedBroadcastScheduler(BroadcastUnitScheduler):
    """Broadcast scheduler with systematic-first, coded-second ordering."""

    def schedule_generation_units(
        self,
        *,
        systematic_units: Sequence[TransmissionUnit],
        coded_units: Sequence[TransmissionUnit],
        transport_epoch_id: int,
        realization_count: int = 1,
    ) -> TransmissionSchedule:
        ordered_units = list(systematic_units) + list(coded_units)
        return self.schedule_units(
            ordered_units,
            transport_epoch_id=transport_epoch_id,
            realization_count=realization_count,
        )
