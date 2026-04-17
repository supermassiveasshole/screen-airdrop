"""Receiver information-layer generation state."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict

from screen_airdrop.common.information import CodedUnit, CodedUnitIdentity, SystematicUnitIdentity
from screen_airdrop.receiver.information.solver_state import SolverState


@dataclass
class GenerationState:
    generation_id: int
    generation_size: int
    symbol_size: int = 0
    systematic_symbols: Dict[int, bytes] = field(default_factory=dict)
    received_source_ids: set[SystematicUnitIdentity] = field(default_factory=set)
    coded_equations: Dict[int, CodedUnit] = field(default_factory=dict)
    coded_equation_count: int = 0
    duplicate_equation_count: int = 0
    received_equation_ids: set[CodedUnitIdentity] = field(default_factory=set)
    solver_rank: int = 0
    conflict_count: int = 0
    invalid_equation_count: int = 0
    dependent_equation_count: int = 0
    decode_complete: bool = False
    decoded_payload_ready: bool = False
    recovered_source_symbols: Dict[int, bytes] = field(default_factory=dict)
    recovered_source_count: int = 0
    last_progress_ts: float = 0.0
    solver_state: SolverState = field(
        default_factory=lambda: SolverState(generation_id=0, generation_size=0)
    )


class GenerationStore(object):
    """Store for per-generation systematic state."""

    def __init__(self) -> None:
        self._generations: Dict[int, GenerationState] = {}

    @property
    def generations(self) -> Dict[int, GenerationState]:
        return self._generations

    def get_or_create(self, generation_id: int, generation_size: int = 0) -> GenerationState:
        generation_id = int(generation_id)
        state = self._generations.get(generation_id)
        if state is None:
            state = GenerationState(
                generation_id=generation_id,
                generation_size=max(0, int(generation_size)),
                solver_state=SolverState(
                    generation_id=generation_id,
                    generation_size=max(0, int(generation_size)),
                ),
            )
            self._generations[generation_id] = state
        elif int(generation_size) > 0 and state.generation_size <= 0:
            state.generation_size = int(generation_size)
            state.solver_state.generation_size = int(generation_size)
        return state

    def update_generation_size(self, generation_id: int, generation_size: int) -> GenerationState:
        state = self.get_or_create(generation_id, generation_size)
        if int(generation_size) > 0:
            state.generation_size = int(generation_size)
            state.solver_state.generation_size = int(generation_size)
            if len(state.systematic_symbols) >= state.generation_size:
                state.decode_complete = True
        return state

    def record_progress(self, state: GenerationState) -> None:
        state.last_progress_ts = float(time.time())
        if state.generation_size > 0 and len(state.recovered_source_symbols) >= state.generation_size:
            state.decode_complete = True

    def record_coded_progress(self, state: GenerationState) -> None:
        state.symbol_size = int(state.solver_state.symbol_size)
        state.systematic_symbols = dict(state.solver_state.systematic_symbols)
        state.recovered_source_symbols = dict(state.solver_state.decoded_source_symbols)
        state.coded_equation_count = int(state.solver_state.raw_coded_count)
        state.solver_rank = int(state.solver_state.rank)
        state.conflict_count = int(state.solver_state.conflict_count)
        state.invalid_equation_count = int(state.solver_state.invalid_equation_count)
        state.dependent_equation_count = int(state.solver_state.dependent_equation_count)
        state.decode_complete = bool(state.solver_state.solvable)
        state.decoded_payload_ready = bool(state.solver_state.solvable)
        state.recovered_source_count = len(state.recovered_source_symbols)
        state.last_progress_ts = float(time.time())

    def bind_solver_state(self, state: GenerationState) -> None:
        state.solver_state = SolverState(
            generation_id=int(state.generation_id),
            generation_size=int(state.generation_size),
            symbol_size=int(state.symbol_size),
            systematic_symbols=dict(state.systematic_symbols),
            equations={},
            received_source_ids=set(state.received_source_ids),
            received_equation_ids=set(state.received_equation_ids),
            decoded_source_symbols=dict(state.recovered_source_symbols),
            rank=int(state.solver_rank),
            dependent_equation_count=int(state.dependent_equation_count),
            solvable=bool(state.decoded_payload_ready),
        )
