"""Sender information-layer helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.sender.information.generation_builder import (
        GenerationPlan,
        build_systematic_generation_plans,
    )
    from screen_airdrop.sender.information.unit_builder import build_systematic_units

__all__ = [
    "GenerationPlan",
    "build_systematic_generation_plans",
    "build_systematic_units",
]


def __getattr__(name):
    if name in {"GenerationPlan", "build_systematic_generation_plans"}:
        from screen_airdrop.sender.information import generation_builder as _generation_builder

        return getattr(_generation_builder, name)
    if name == "build_systematic_units":
        from screen_airdrop.sender.information.unit_builder import build_systematic_units

        return build_systematic_units
    raise AttributeError(name)
