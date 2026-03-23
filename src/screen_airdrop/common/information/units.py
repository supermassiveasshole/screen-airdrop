"""Shared information-layer transmission unit models."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class UnitType(enum.Enum):
    """Information-layer unit type."""

    SYSTEMATIC = "systematic"
    CODED = "coded"


@dataclass(frozen=True)
class TransmissionUnit:
    """Semantic transmission object carried by visual transport."""

    session_id: int
    generation_id: int
    generation_size: int
    payload_size: int
    payload: bytes
    unit_type: UnitType

    def __post_init__(self) -> None:
        if int(self.payload_size) != len(self.payload):
            raise ValueError("payload_size must equal len(payload)")
        if int(self.generation_id) < 0:
            raise ValueError("generation_id must be non-negative")
        if int(self.generation_size) < 0:
            raise ValueError("generation_size must be non-negative")


@dataclass(frozen=True)
class SystematicUnit(TransmissionUnit):
    """Systematic source-symbol transmission unit."""

    source_index: int
    unit_type: UnitType = field(init=False, default=UnitType.SYSTEMATIC)

    def __post_init__(self) -> None:
        super().__post_init__()
        if int(self.source_index) < 0:
            raise ValueError("source_index must be non-negative")

