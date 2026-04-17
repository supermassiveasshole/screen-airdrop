"""Receiver information-layer unit acceptance."""

from __future__ import annotations

import enum

from screen_airdrop.common.information import (
    CodedUnit,
    SystematicUnit,
    TransmissionUnit,
    UnitType,
    coded_unit_identity,
    systematic_unit_identity,
)
from screen_airdrop.receiver.information.generation_store import GenerationStore


class AcceptResult(enum.Enum):
    ACCEPTED_SYSTEMATIC = "accepted_systematic"
    ACCEPTED_CODED = "accepted_coded"
    DUPLICATE = "duplicate"


class UnitAcceptor(object):
    """Information-layer acceptor for systematic and coded units."""

    def __init__(self, generation_store: GenerationStore) -> None:
        self._generation_store = generation_store

    def accept(
        self,
        unit: TransmissionUnit,
        *,
        generation_size_hint: int = 0,
    ) -> AcceptResult:
        generation_size = (
            int(unit.generation_size)
            if int(unit.generation_size) > 0
            else int(generation_size_hint)
        )
        state = self._generation_store.get_or_create(int(unit.generation_id), generation_size)

        if unit.unit_type == UnitType.SYSTEMATIC:
            if not isinstance(unit, SystematicUnit):
                raise TypeError("systematic unit must be SystematicUnit")
            identity = systematic_unit_identity(unit)
            if identity in state.received_source_ids or int(unit.source_index) in state.systematic_symbols:
                return AcceptResult.DUPLICATE

            state.received_source_ids.add(identity)
            state.systematic_symbols[int(unit.source_index)] = unit.payload
            state.recovered_source_symbols[int(unit.source_index)] = unit.payload
            state.solver_state.systematic_symbols[int(unit.source_index)] = unit.payload
            state.solver_state.decoded_source_symbols[int(unit.source_index)] = unit.payload
            state.solver_state.received_source_ids.add(identity)
            self._generation_store.record_progress(state)
            return AcceptResult.ACCEPTED_SYSTEMATIC

        if unit.unit_type == UnitType.CODED:
            if not isinstance(unit, CodedUnit):
                raise TypeError("coded unit must be CodedUnit")
            identity = coded_unit_identity(unit)
            if identity in state.received_equation_ids or int(unit.equation_id) in state.coded_equations:
                state.duplicate_equation_count += 1
                return AcceptResult.DUPLICATE

            state.received_equation_ids.add(identity)
            state.coded_equations[int(unit.equation_id)] = unit
            state.solver_state.received_equation_ids.add(identity)
            self._generation_store.record_coded_progress(state)
            return AcceptResult.ACCEPTED_CODED

        raise NotImplementedError("unsupported information unit type")
