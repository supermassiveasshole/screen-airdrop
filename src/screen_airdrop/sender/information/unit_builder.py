"""Build sender-side information-layer units."""

from __future__ import annotations

from typing import Iterable, List

from screen_airdrop.common.information import SystematicUnit


def build_systematic_units(
    *,
    session_id: int,
    generation_id: int,
    generation_size: int,
    payload_chunks: Iterable[bytes],
) -> List[SystematicUnit]:
    """Map payload chunks to systematic information units."""
    units: List[SystematicUnit] = []
    for source_index, payload in enumerate(payload_chunks, start=1):
        units.append(
            SystematicUnit(
                session_id=int(session_id),
                generation_id=int(generation_id),
                generation_size=int(generation_size),
                source_index=int(source_index),
                payload_size=len(payload),
                payload=payload,
            )
        )
    return units
