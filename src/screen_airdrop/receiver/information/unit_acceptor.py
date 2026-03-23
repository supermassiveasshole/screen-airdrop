"""Receiver information-layer unit acceptance."""

from __future__ import annotations

import enum

from screen_airdrop.common.information import (
    SystematicUnit,
    TransmissionUnit,
    UnitType,
    systematic_unit_identity,
)
from screen_airdrop.receiver.information.generation_store import GenerationStore


class AcceptResult(enum.Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"


class UnitAcceptor(object):
    """Systematic-only information-layer acceptor."""

    def __init__(self, generation_store: GenerationStore) -> None:
        self._generation_store = generation_store

    def accept(
        self,
        unit: TransmissionUnit,
        *,
        generation_size_hint: int = 0,
    ) -> AcceptResult:
        if unit.unit_type != UnitType.SYSTEMATIC:
            raise NotImplementedError("only systematic units are supported in this phase")
        if not isinstance(unit, SystematicUnit):
            raise TypeError("systematic unit must be SystematicUnit")

        generation_size = int(unit.generation_size) if int(unit.generation_size) > 0 else int(generation_size_hint)
        state = self._generation_store.get_or_create(int(unit.generation_id), generation_size)
        identity = systematic_unit_identity(unit)
        if identity in state.received_source_ids or int(unit.source_index) in state.systematic_symbols:
            return AcceptResult.DUPLICATE

        state.received_source_ids.add(identity)
        state.systematic_symbols[int(unit.source_index)] = unit.payload
        self._generation_store.record_progress(state)
        return AcceptResult.ACCEPTED
