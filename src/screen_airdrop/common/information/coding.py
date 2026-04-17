"""Shared information-layer coded-equation metadata helpers."""

from __future__ import annotations

import enum
import random
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple


@dataclass(frozen=True)
class CodingSeedMetadata:
    """Seed-first coded-equation metadata skeleton."""

    equation_id: int
    coding_seed: int
    degree: int
    coding_scheme: "CodingScheme" = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if int(self.equation_id) < 0:
            raise ValueError("equation_id must be non-negative")
        if int(self.coding_seed) < 0:
            raise ValueError("coding_seed must be non-negative")
        if int(self.degree) <= 0:
            raise ValueError("degree must be positive")
        scheme = self.coding_scheme
        if scheme is None:
            scheme = CodingScheme.GF256_SEED_V2
        elif not isinstance(scheme, CodingScheme):
            scheme = CodingScheme(str(scheme))
        object.__setattr__(self, "coding_scheme", scheme)


class CodingScheme(enum.Enum):
    """Supported coded-equation schemes."""

    GF256_SEED_V1 = "gf256_seed_v1"
    GF256_SEED_V2 = "gf256_seed_v2"


EquationTerm = Tuple[int, int]

_GF256_PRIMITIVE_POLY = 0x11D
_GF256_EXP_TABLE: List[int] = [0] * 512
_GF256_LOG_TABLE: List[int] = [0] * 256

_value = 1
for _index in range(255):
    _GF256_EXP_TABLE[_index] = _value
    _GF256_LOG_TABLE[_value] = _index
    _value <<= 1
    if _value & 0x100:
        _value ^= _GF256_PRIMITIVE_POLY
for _index in range(255, 512):
    _GF256_EXP_TABLE[_index] = _GF256_EXP_TABLE[_index - 255]


def expand_equation_terms(
    *,
    generation_size: int,
    coding_seed: int,
    degree: int,
    coding_scheme: CodingScheme = CodingScheme.GF256_SEED_V2,
) -> Tuple[EquationTerm, ...]:
    """Expand seed-first coded metadata into ordered GF(256) equation terms."""
    if not isinstance(coding_scheme, CodingScheme):
        coding_scheme = CodingScheme(str(coding_scheme))
    size = int(generation_size)
    if size <= 0:
        return ()
    usable_degree = int(degree)
    if usable_degree <= 0 or usable_degree > size:
        raise ValueError("degree must be within [1, generation_size]")
    indices = _expand_equation_indices_for_scheme(
        generation_size=size,
        coding_seed=int(coding_seed),
        degree=usable_degree,
        coding_scheme=coding_scheme,
    )
    coefficient_rng = random.Random(
        _coefficient_seed(
            coding_seed=int(coding_seed),
            generation_size=size,
            degree=usable_degree,
            coding_scheme=coding_scheme,
        )
    )
    return tuple(
        (int(index), int(coefficient_rng.randrange(1, 256)))
        for index in indices
    )


def expand_equation_indices(
    *,
    generation_size: int,
    coding_seed: int,
    degree: int,
    coding_scheme: CodingScheme = CodingScheme.GF256_SEED_V2,
) -> Tuple[int, ...]:
    """Legacy helper returning only selected source indices."""
    return tuple(
        source_index
        for source_index, _coefficient in expand_equation_terms(
            generation_size=generation_size,
            coding_seed=coding_seed,
            degree=degree,
            coding_scheme=coding_scheme,
        )
    )


def _expand_equation_indices_for_scheme(
    *,
    generation_size: int,
    coding_seed: int,
    degree: int,
    coding_scheme: CodingScheme,
) -> Tuple[int, ...]:
    if coding_scheme is CodingScheme.GF256_SEED_V1:
        rng = random.Random(int(coding_seed))
        return tuple(sorted(rng.sample(range(1, generation_size + 1), degree)))
    if coding_scheme is CodingScheme.GF256_SEED_V2:
        return _expand_equation_indices_v2(
            generation_size=generation_size,
            coding_seed=coding_seed,
            degree=degree,
        )
    raise ValueError("unsupported coding_scheme")


def _expand_equation_indices_v2(
    *,
    generation_size: int,
    coding_seed: int,
    degree: int,
) -> Tuple[int, ...]:
    group_count = (int(generation_size) + int(degree) - 1) // int(degree)
    round_index = int(coding_seed) // group_count
    group_index = int(coding_seed) % group_count
    base_start = (round_index + (group_index * int(degree))) % int(generation_size)
    selected: List[int] = []
    seen = set()
    cursor = int(base_start)
    while len(selected) < int(degree):
        source_index = cursor + 1
        if source_index not in seen:
            selected.append(source_index)
            seen.add(source_index)
        cursor = (cursor + 1) % int(generation_size)
    return tuple(sorted(selected))


def _coefficient_seed(
    *,
    coding_seed: int,
    generation_size: int,
    degree: int,
    coding_scheme: CodingScheme,
) -> int:
    scheme_tag = 0x5631 if coding_scheme is CodingScheme.GF256_SEED_V1 else 0x5632
    mixed = _mix_u32(int(coding_seed) ^ scheme_tag)
    mixed = _mix_u32(mixed ^ ((int(generation_size) & 0xFFFF) << 16) ^ (int(degree) & 0xFFFF))
    return int(mixed)


def _mix_u32(value: int) -> int:
    mixed = int(value) & 0xFFFFFFFF
    mixed ^= mixed >> 16
    mixed = (mixed * 0x7FEB352D) & 0xFFFFFFFF
    mixed ^= mixed >> 15
    mixed = (mixed * 0x846CA68B) & 0xFFFFFFFF
    mixed ^= mixed >> 16
    return int(mixed)


def gf256_add(lhs: int, rhs: int) -> int:
    """GF(256) addition, equivalent to XOR."""
    return int(lhs) ^ int(rhs)


def gf256_mul(lhs: int, rhs: int) -> int:
    """Multiply two GF(256) elements."""
    left = int(lhs) & 0xFF
    right = int(rhs) & 0xFF
    if left == 0 or right == 0:
        return 0
    return int(_GF256_EXP_TABLE[_GF256_LOG_TABLE[left] + _GF256_LOG_TABLE[right]])


def gf256_inv(value: int) -> int:
    """Return the multiplicative inverse of a non-zero GF(256) element."""
    int_value = int(value) & 0xFF
    if int_value == 0:
        raise ZeroDivisionError("cannot invert zero in GF(256)")
    return int(_GF256_EXP_TABLE[255 - _GF256_LOG_TABLE[int_value]])


def gf256_div(lhs: int, rhs: int) -> int:
    """Divide one GF(256) element by another non-zero element."""
    return gf256_mul(int(lhs), gf256_inv(int(rhs)))


def gf256_scale_payload(payload: bytes, coefficient: int) -> bytes:
    """Scale a payload by one GF(256) coefficient."""
    factor = int(coefficient) & 0xFF
    if factor == 0:
        return b"\x00" * len(payload)
    if factor == 1:
        return bytes(payload)
    return bytes(gf256_mul(byte, factor) for byte in payload)


def gf256_linear_combine(terms: Sequence[Tuple[int, bytes]]) -> bytes:
    """Compute a GF(256) linear combination of equally sized payloads."""
    term_list = list(terms)
    if not term_list:
        return b""
    width = len(term_list[0][1])
    if any(len(payload) != width for _, payload in term_list):
        raise ValueError("all payloads must have the same size")
    result = bytearray(width)
    for coefficient, payload in term_list:
        scaled = gf256_scale_payload(payload, int(coefficient))
        for index, value in enumerate(scaled):
            result[index] ^= value
    return bytes(result)


def xor_payloads(payloads: Iterable[bytes]) -> bytes:
    """Legacy helper for XOR-only payload combinations."""
    payload_list = list(payloads)
    if not payload_list:
        return b""
    width = max(len(payload) for payload in payload_list)
    result = bytearray(width)
    for payload in payload_list:
        for idx in range(width):
            result[idx] ^= payload[idx] if idx < len(payload) else 0
    return bytes(result)
