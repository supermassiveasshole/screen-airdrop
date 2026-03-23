"""Broadcast scheduling policy for sender-side control/data sequencing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BroadcastSchedule:
    """Control-plane scheduling knobs shared across physical protocols."""

    sync_frames: int = 30
    control_burst_repeat: int = 5
    data_realizations: int = 1

    def normalized_sync_frames(self) -> int:
        return max(0, int(self.sync_frames))

    def normalized_control_burst_repeat(self) -> int:
        return max(1, int(self.control_burst_repeat))

    def normalized_data_realizations(self) -> int:
        return max(1, int(self.data_realizations))
