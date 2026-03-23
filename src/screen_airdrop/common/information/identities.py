"""Shared information-layer identity helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from screen_airdrop.common.information.units import SystematicUnit, UnitType


@dataclass(frozen=True)
class UnitIdentity:
    """Current systematic-only information-unit identity."""

    generation_id: int
    source_index: int
    unit_type: UnitType = field(default=UnitType.SYSTEMATIC)


def systematic_unit_identity(unit: SystematicUnit) -> UnitIdentity:
    """Build the systematic identity key for a unit."""
    return UnitIdentity(
        generation_id=int(unit.generation_id),
        source_index=int(unit.source_index),
    )

