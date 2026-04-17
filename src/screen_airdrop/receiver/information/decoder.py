"""Receiver information-layer ingest and sparse-XOR solve entry."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Dict

from screen_airdrop.common.information import CodedUnit, SystematicUnit, TransmissionUnit, UnitType
from screen_airdrop.receiver.information.generation_store import GenerationStore
from screen_airdrop.receiver.information.solver_state import SolverCodedStatus
from screen_airdrop.receiver.information.unit_acceptor import AcceptResult, UnitAcceptor


class IngestStatus(enum.Enum):
    DUPLICATE = "duplicate"
    ACCEPTED_SYSTEMATIC = "accepted_systematic"
    ACCEPTED_CODED = "accepted_coded"
    RECOVERED_NEW_SYMBOLS = "recovered_new_symbols"
    GENERATION_COMPLETE = "generation_complete"
    INVALID_CODED = "invalid_coded"
    CONFLICTING_CODED = "conflicting_coded"


@dataclass(frozen=True)
class IngestResult:
    status: IngestStatus
    recovered_source_symbols: Dict[int, bytes]
    generation_complete: bool
    rank_increased: bool = False
    dependent_equation: bool = False
    error: str = ""


class InformationDecoder(object):
    """Information-layer ingest wrapper with sparse-XOR recovery."""

    def __init__(
        self,
        generation_store: GenerationStore,
        unit_acceptor: UnitAcceptor | None = None,
    ) -> None:
        self._generation_store = generation_store
        self._unit_acceptor = (
            unit_acceptor if unit_acceptor is not None else UnitAcceptor(generation_store)
        )

    def ingest(
        self,
        unit: TransmissionUnit,
        *,
        generation_size_hint: int = 0,
    ) -> IngestResult:
        accept_result = self._unit_acceptor.accept(
            unit,
            generation_size_hint=generation_size_hint,
        )
        state = self._generation_store.get_or_create(
            int(unit.generation_id),
            int(unit.generation_size) if int(unit.generation_size) > 0 else int(generation_size_hint),
        )

        if accept_result == AcceptResult.DUPLICATE:
            return IngestResult(
                status=IngestStatus.DUPLICATE,
                recovered_source_symbols={},
                generation_complete=bool(state.decode_complete),
            )

        if unit.unit_type == UnitType.SYSTEMATIC:
            if not isinstance(unit, SystematicUnit):
                raise TypeError("systematic unit must be SystematicUnit")
            if int(unit.generation_size) <= 0 and int(state.generation_size) > 0:
                unit = SystematicUnit(
                    session_id=int(unit.session_id),
                    generation_id=int(unit.generation_id),
                    generation_size=int(state.generation_size),
                    source_index=int(unit.source_index),
                    payload_size=len(unit.payload),
                    payload=unit.payload,
                )
            recovered_indices = state.solver_state.ingest_systematic(unit)
            self._sync_state(state)
            status = (
                IngestStatus.GENERATION_COMPLETE
                if state.decode_complete
                else IngestStatus.ACCEPTED_SYSTEMATIC
            )
            return IngestResult(
                status=status,
                recovered_source_symbols={
                    index: state.recovered_source_symbols[index]
                    for index in recovered_indices
                    if index in state.recovered_source_symbols
                },
                generation_complete=bool(state.decode_complete),
            )

        if unit.unit_type == UnitType.CODED:
            if not isinstance(unit, CodedUnit):
                raise TypeError("coded unit must be CodedUnit")
            if int(unit.generation_size) <= 0 and int(state.generation_size) > 0:
                unit = CodedUnit(
                    session_id=int(unit.session_id),
                    generation_id=int(unit.generation_id),
                    generation_size=int(state.generation_size),
                    equation_id=int(unit.equation_id),
                    coding_seed=int(unit.coding_seed),
                    degree=int(unit.degree),
                    coding_scheme=unit.coding_scheme,
                    payload_size=len(unit.payload),
                    payload=unit.payload,
                )
            coded_result = state.solver_state.ingest_coded(unit)
            self._sync_state(state)
            if coded_result.status == SolverCodedStatus.INVALID:
                status = IngestStatus.INVALID_CODED
            elif coded_result.status == SolverCodedStatus.CONFLICTING:
                status = IngestStatus.CONFLICTING_CODED
            elif state.decode_complete:
                status = IngestStatus.GENERATION_COMPLETE
            elif coded_result.recovered_indices:
                status = IngestStatus.RECOVERED_NEW_SYMBOLS
            else:
                status = IngestStatus.ACCEPTED_CODED
            return IngestResult(
                status=status,
                recovered_source_symbols={
                    index: state.recovered_source_symbols[index]
                    for index in coded_result.recovered_indices
                    if index in state.recovered_source_symbols
                },
                generation_complete=bool(state.decode_complete),
                rank_increased=bool(coded_result.rank_increased),
                dependent_equation=bool(coded_result.dependent_equation),
                error=str(coded_result.error),
            )

        raise NotImplementedError("unsupported information unit type")

    def _sync_state(self, state) -> None:
        state.symbol_size = int(state.solver_state.symbol_size)
        state.systematic_symbols = dict(state.solver_state.systematic_symbols)
        state.recovered_source_symbols = dict(state.solver_state.decoded_source_symbols)
        state.received_source_ids = set(state.solver_state.received_source_ids)
        state.solver_rank = int(state.solver_state.rank)
        state.decode_complete = bool(state.solver_state.solvable)
        state.decoded_payload_ready = bool(state.solver_state.solvable)
        self._generation_store.record_coded_progress(state)
