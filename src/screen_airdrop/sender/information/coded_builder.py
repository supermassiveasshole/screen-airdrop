"""Sender-side coded-unit skeleton builder."""

from __future__ import annotations

from typing import List, Sequence

from screen_airdrop.common.information import (
    CodedUnit,
    CodingScheme,
    SystematicUnit,
    expand_equation_terms,
    gf256_linear_combine,
)


def build_coded_unit(
    *,
    session_id: int,
    generation_id: int,
    generation_size: int,
    source_units: Sequence[SystematicUnit],
    equation_id: int,
    coding_seed: int,
    degree: int = 2,
    coding_scheme: CodingScheme = CodingScheme.GF256_SEED_V2,
) -> CodedUnit:
    """Build one deterministic GF(256) coded unit."""
    if not source_units:
        raise ValueError("source_units must not be empty")
    if int(generation_size) != len(source_units):
        raise ValueError("generation_size must equal len(source_units)")
    payload_sizes = {len(unit.payload) for unit in source_units}
    if len(payload_sizes) != 1:
        raise ValueError("all source unit payloads must have the same size")
    if int(degree) <= 0:
        raise ValueError("degree must be positive")
    if int(degree) > len(source_units):
        raise ValueError("degree must not exceed generation_size")
    usable_degree = int(degree)
    payload = _build_coded_payload(
        source_units=source_units,
        generation_size=int(generation_size),
        coding_seed=int(coding_seed),
        degree=usable_degree,
        coding_scheme=coding_scheme,
    )
    return CodedUnit(
        session_id=int(session_id),
        generation_id=int(generation_id),
        generation_size=int(generation_size),
        equation_id=int(equation_id),
        coding_seed=int(coding_seed),
        degree=usable_degree,
        coding_scheme=coding_scheme,
        payload_size=len(payload),
        payload=payload,
    )


def build_coded_units(
    *,
    session_id: int,
    generation_id: int,
    generation_size: int,
    source_units: Sequence[SystematicUnit],
    count: int = 1,
    coding_seed_start: int = 0,
    degree: int = 2,
    coding_scheme: CodingScheme = CodingScheme.GF256_SEED_V2,
) -> List[CodedUnit]:
    """Build deterministic GF(256) coded units for one generation."""
    usable_count = max(0, int(count))
    return [
        build_coded_unit(
            session_id=int(session_id),
            generation_id=int(generation_id),
            generation_size=int(generation_size),
            source_units=source_units,
            equation_id=offset,
            coding_seed=int(coding_seed_start) + offset,
            degree=int(degree),
            coding_scheme=coding_scheme,
        )
        for offset in range(usable_count)
    ]


def build_placeholder_coded_units(**kwargs) -> List[CodedUnit]:
    """Backward-compatible alias for the deterministic coded builder."""
    return build_coded_units(**kwargs)


def _build_coded_payload(
    *,
    source_units: Sequence[SystematicUnit],
    generation_size: int,
    coding_seed: int,
    degree: int,
    coding_scheme: CodingScheme,
) -> bytes:
    """Build the deterministic GF(256) coded payload."""
    by_index = {int(unit.source_index): unit for unit in source_units}
    selected_terms = expand_equation_terms(
        generation_size=int(generation_size),
        coding_seed=int(coding_seed),
        degree=int(degree),
        coding_scheme=coding_scheme,
    )
    selected_payloads = [
        (coefficient, by_index[index].payload)
        for index, coefficient in selected_terms
        if index in by_index
    ]
    if len(selected_payloads) != len(selected_terms):
        raise ValueError("selected source index missing from generation")
    return gf256_linear_combine(selected_payloads)
