from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.sender.scheduling.broadcast_schedule import BroadcastSchedule
    from screen_airdrop.sender.scheduling.control_payloads import (
        build_generation_control_payload,
        build_layout_control_payload,
        build_session_control_payload,
    )
    from screen_airdrop.sender.scheduling.unit_schedule import BroadcastUnitScheduler

__all__ = [
    "BroadcastSchedule",
    "BroadcastUnitScheduler",
    "build_generation_control_payload",
    "build_layout_control_payload",
    "build_session_control_payload",
]


def __getattr__(name):
    if name == "BroadcastSchedule":
        from screen_airdrop.sender.scheduling.broadcast_schedule import BroadcastSchedule

        return BroadcastSchedule
    if name in {
        "build_generation_control_payload",
        "build_layout_control_payload",
        "build_session_control_payload",
    }:
        from screen_airdrop.sender.scheduling import control_payloads as _control_payloads

        return getattr(_control_payloads, name)
    if name == "BroadcastUnitScheduler":
        from screen_airdrop.sender.scheduling.unit_schedule import BroadcastUnitScheduler

        return BroadcastUnitScheduler
    raise AttributeError(name)
