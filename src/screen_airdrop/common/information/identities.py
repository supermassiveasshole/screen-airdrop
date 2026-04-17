"""Shared information-layer identity helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

from screen_airdrop.common.information.units import CodedUnit, SystematicUnit, UnitType


@dataclass(frozen=True)
class SystematicUnitIdentity:
    """Identity key for a systematic information unit."""

    generation_id: int
    source_index: int
    unit_type: UnitType = field(default=UnitType.SYSTEMATIC)


@dataclass(frozen=True)
class CodedUnitIdentity:
    """Identity key for a coded information unit."""

    generation_id: int
    equation_id: int
    unit_type: UnitType = field(default=UnitType.CODED)


UnitIdentity = Union[SystematicUnitIdentity, CodedUnitIdentity]


def systematic_unit_identity(unit: SystematicUnit) -> SystematicUnitIdentity:
    """Build the systematic identity key for a unit."""
    return SystematicUnitIdentity(
        generation_id=int(unit.generation_id),
        source_index=int(unit.source_index),
    )


def coded_unit_identity(unit: CodedUnit) -> CodedUnitIdentity:
    """Build the coded identity key for a unit."""
    return CodedUnitIdentity(
        generation_id=int(unit.generation_id),
        equation_id=int(unit.equation_id),
    )
