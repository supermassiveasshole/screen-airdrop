"""Receiver information-layer generation state."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict

from screen_airdrop.common.information import UnitIdentity


@dataclass
class GenerationState:
    generation_id: int
    generation_size: int
    systematic_symbols: Dict[int, bytes] = field(default_factory=dict)
    received_source_ids: set[UnitIdentity] = field(default_factory=set)
    decode_complete: bool = False
    last_progress_ts: float = 0.0


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
            )
            self._generations[generation_id] = state
        elif int(generation_size) > 0 and state.generation_size <= 0:
            state.generation_size = int(generation_size)
        return state

    def update_generation_size(self, generation_id: int, generation_size: int) -> GenerationState:
        state = self.get_or_create(generation_id, generation_size)
        if int(generation_size) > 0:
            state.generation_size = int(generation_size)
            if len(state.systematic_symbols) >= state.generation_size:
                state.decode_complete = True
        return state

    def record_progress(self, state: GenerationState) -> None:
        state.last_progress_ts = float(time.time())
        if state.generation_size > 0 and len(state.systematic_symbols) >= state.generation_size:
            state.decode_complete = True
