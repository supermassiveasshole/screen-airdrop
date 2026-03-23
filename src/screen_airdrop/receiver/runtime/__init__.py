"""Runtime components for screen live capture pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.receiver.runtime.slot_manager import SlotManager, SlotState
    from screen_airdrop.receiver.runtime.stats import ScreenLiveRuntimeStats

__all__ = [
    "SlotManager",
    "SlotState",
    "ScreenLiveRuntimeStats",
]


def __getattr__(name):
    if name in {"SlotManager", "SlotState"}:
        from screen_airdrop.receiver.runtime import slot_manager as _slot_manager

        return getattr(_slot_manager, name)
    if name == "ScreenLiveRuntimeStats":
        from screen_airdrop.receiver.runtime.stats import ScreenLiveRuntimeStats

        return ScreenLiveRuntimeStats
    raise AttributeError(name)
