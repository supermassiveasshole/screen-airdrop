"""Sender information-layer helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.sender.information.coded_builder import (
        build_coded_unit,
        build_coded_units,
        build_placeholder_coded_units,
    )
    from screen_airdrop.sender.information.generation_builder import (
        GenerationPlan,
        build_systematic_generation_plans,
    )
    from screen_airdrop.sender.information.unit_builder import build_systematic_units

__all__ = [
    "build_coded_unit",
    "build_coded_units",
    "build_placeholder_coded_units",
    "GenerationPlan",
    "build_systematic_generation_plans",
    "build_systematic_units",
]


def __getattr__(name):
    if name in {
        "build_coded_unit",
        "build_coded_units",
        "build_placeholder_coded_units",
    }:
        from screen_airdrop.sender.information import coded_builder as _coded_builder

        return getattr(_coded_builder, name)
    if name in {"GenerationPlan", "build_systematic_generation_plans"}:
        from screen_airdrop.sender.information import generation_builder as _generation_builder

        return getattr(_generation_builder, name)
    if name == "build_systematic_units":
        from screen_airdrop.sender.information.unit_builder import build_systematic_units

        return build_systematic_units
    raise AttributeError(name)
