"""Build sender-side systematic generation plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence

from screen_airdrop.common.information import SystematicUnit
from screen_airdrop.sender.information.unit_builder import build_systematic_units


@dataclass(frozen=True)
class GenerationPlan:
    """One non-overlapping systematic generation."""

    generation_id: int
    generation_size: int
    source_index_base: int
    source_units: Sequence[SystematicUnit]


def build_systematic_generation_plans(
    *,
    session_id: int,
    payload_chunks: Iterable[bytes],
    systematic_generation_size: int,
) -> List[GenerationPlan]:
    """Split payload chunks into ordered non-overlapping systematic generations."""
    all_chunks = list(payload_chunks)
    if not all_chunks:
        return []

    window = max(1, int(systematic_generation_size))
    plans: List[GenerationPlan] = []
    for generation_id, start in enumerate(range(0, len(all_chunks), window)):
        generation_chunks = all_chunks[start : start + window]
        source_units = build_systematic_units(
            session_id=int(session_id),
            generation_id=int(generation_id),
            generation_size=len(generation_chunks),
            payload_chunks=generation_chunks,
        )
        plans.append(
            GenerationPlan(
                generation_id=int(generation_id),
                generation_size=len(generation_chunks),
                source_index_base=start + 1,
                source_units=source_units,
            )
        )
    return plans
