"""Sender-side systematic unit scheduling helpers."""

from __future__ import annotations

from typing import List, Sequence

from screen_airdrop.common.information import TransmissionUnit
from screen_airdrop.common.scheduling import ScheduledUnit, TransmissionSchedule, UnitScheduler


class BroadcastUnitScheduler(UnitScheduler):
    """Default systematic-only broadcast scheduler."""

    def schedule_units(
        self,
        units: Sequence[TransmissionUnit],
        *,
        transport_epoch_id: int,
        realization_count: int = 1,
    ) -> TransmissionSchedule:
        scheduled: List[ScheduledUnit] = []
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
