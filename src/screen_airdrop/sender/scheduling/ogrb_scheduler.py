"""Sender-side OGRB scheduler skeleton."""

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


class OgrbSkeletonScheduler(UnitScheduler):
    """Generation-aware placeholder scheduler for future OGRB work."""

    def schedule_units(
        self,
        units: Sequence[TransmissionUnit],
        *,
        transport_epoch_id: int,
        realization_count: int = 1,
        generation_candidates: Optional[Sequence[GenerationUnitCandidate]] = None,
        scheduler_context: Optional[SchedulerContext] = None,
    ) -> TransmissionSchedule:
        if generation_candidates:
            ordered_units: List[TransmissionUnit] = []
            for candidate in generation_candidates:
                ordered_units.extend(candidate.units)
            units = ordered_units
        if scheduler_context is not None:
            transport_epoch_id = int(scheduler_context.transport_epoch_id)
            realization_count = int(scheduler_context.realization_count)
        count = max(1, int(realization_count))
        scheduled = []
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
