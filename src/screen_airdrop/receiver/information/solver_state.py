"""Receiver information-layer GF(256) solver state."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict, Iterable, Mapping, Optional, Set, Tuple

from screen_airdrop.common.information import (
    CodedUnit,
    CodedUnitIdentity,
    EquationTerm,
    SystematicUnit,
    SystematicUnitIdentity,
    expand_equation_terms,
    gf256_div,
    gf256_linear_combine,
    gf256_mul,
    gf256_scale_payload,
)


@dataclass(frozen=True)
class Gf256EquationRow:
    """One GF(256) equation over generation-local source indices."""

    terms: Tuple[EquationTerm, ...]
    rhs_payload: bytes


class SolverCodedStatus(enum.Enum):
    ACCEPTED = "accepted"
    RECOVERED = "recovered"
    INVALID = "invalid"
    CONFLICTING = "conflicting"


@dataclass(frozen=True)
class SolverCodedResult:
    status: SolverCodedStatus
    recovered_indices: Tuple[int, ...] = ()
    rank_increased: bool = False
    dependent_equation: bool = False
    error: str = ""


@dataclass
class SolverState:
    """Generation-local coded-equation tracking and recovery state."""

    generation_id: int
    generation_size: int
    symbol_size: int = 0
    systematic_symbols: Dict[int, bytes] = field(default_factory=dict)
    equations: Dict[int, Gf256EquationRow] = field(default_factory=dict)
    received_source_ids: Set[SystematicUnitIdentity] = field(default_factory=set)
    received_equation_ids: Set[CodedUnitIdentity] = field(default_factory=set)
    raw_coded_count: int = 0
    rank: int = 0
    conflict_count: int = 0
    invalid_equation_count: int = 0
    dependent_equation_count: int = 0
    solvable: bool = False
    decoded_source_symbols: Dict[int, bytes] = field(default_factory=dict)

    def ingest_systematic(self, unit: SystematicUnit) -> Tuple[int, ...]:
        """Record a known source symbol and propagate recoveries."""
        self._update_symbol_size(unit.payload, strict=bool(self.equations))
        source_index = int(unit.source_index)
        self.systematic_symbols[source_index] = unit.payload
        self.decoded_source_symbols[source_index] = unit.payload
        self.received_source_ids.add(
            SystematicUnitIdentity(
                generation_id=int(unit.generation_id),
                source_index=source_index,
            )
        )
        return self._solve()

    def ingest_coded(self, unit: CodedUnit) -> SolverCodedResult:
        """Record a coded equation and attempt GF(256) recovery."""
        try:
            self._update_symbol_size(unit.payload, strict=True)
        except ValueError as exc:
            self.invalid_equation_count += 1
            return SolverCodedResult(status=SolverCodedStatus.INVALID, error=str(exc))
        if int(unit.degree) <= 0:
            self.invalid_equation_count += 1
            return SolverCodedResult(
                status=SolverCodedStatus.INVALID,
                error="degree must be positive",
            )
        try:
            terms = expand_equation_terms(
                generation_size=int(unit.generation_size),
                coding_seed=int(unit.coding_seed),
                degree=int(unit.degree),
                coding_scheme=unit.coding_scheme,
            )
        except ValueError as exc:
            self.invalid_equation_count += 1
            return SolverCodedResult(status=SolverCodedStatus.INVALID, error=str(exc))
        if not terms:
            self.invalid_equation_count += 1
            return SolverCodedResult(
                status=SolverCodedStatus.INVALID,
                error="coded equation expanded to no source terms",
            )
        conflict = self._equation_conflicts_with_known(
            terms=terms,
            rhs_payload=unit.payload,
        )
        if conflict:
            self.conflict_count += 1
            return SolverCodedResult(
                status=SolverCodedStatus.CONFLICTING,
                error=conflict,
            )
        self.received_equation_ids.add(
            CodedUnitIdentity(
                generation_id=int(unit.generation_id),
                equation_id=int(unit.equation_id),
            )
        )
        self.equations[int(unit.equation_id)] = Gf256EquationRow(
            terms=terms,
            rhs_payload=unit.payload,
        )
        self.raw_coded_count += 1
        previous_rank = int(self.rank)
        recovered = self._solve()
        rank_increased = int(self.rank) > previous_rank
        dependent_equation = not recovered and not rank_increased
        return SolverCodedResult(
            status=SolverCodedStatus.RECOVERED if recovered else SolverCodedStatus.ACCEPTED,
            recovered_indices=recovered,
            rank_increased=rank_increased,
            dependent_equation=dependent_equation,
        )

    def snapshot_known_symbols(self) -> Dict[int, bytes]:
        return dict(self.decoded_source_symbols)

    def _solve(self) -> Tuple[int, ...]:
        """Solve as far as possible using GF(256) elimination."""
        known = dict(self.decoded_source_symbols)
        pivot_rows: Dict[int, Gf256EquationRow] = {}
        for equation_id in sorted(self.equations):
            reduced = self._reduce_row(self.equations[equation_id], known, pivot_rows)
            if reduced is None or not reduced.terms:
                continue
            pivot_rows[int(reduced.terms[0][0])] = reduced

        basis_rank = len(pivot_rows)
        recovered: Dict[int, bytes] = {}
        changed = True
        while changed:
            changed = False
            for pivot in sorted(pivot_rows.keys(), reverse=True):
                row = pivot_rows[pivot]
                unresolved = [
                    (source_index, coefficient)
                    for source_index, coefficient in row.terms
                    if source_index not in known
                ]
                if len(unresolved) != 1:
                    continue
                target, coefficient = unresolved[0]
                known_terms = [
                    (coef, known[source_index])
                    for source_index, coef in row.terms
                    if source_index in known
                ]
                rhs = row.rhs_payload
                if known_terms:
                    rhs = gf256_linear_combine([(1, rhs), *known_terms])
                payload = gf256_scale_payload(rhs, gf256_div(1, int(coefficient)))
                existing = known.get(int(target))
                if existing is not None:
                    if existing != payload:
                        continue
                    continue
                known[int(target)] = payload
                recovered[int(target)] = payload
                changed = True
            if changed:
                new_pivot_rows: Dict[int, Gf256EquationRow] = {}
                for equation_id in sorted(self.equations):
                    reduced = self._reduce_row(self.equations[equation_id], known, new_pivot_rows)
                    if reduced is None or not reduced.terms:
                        continue
                    new_pivot_rows[int(reduced.terms[0][0])] = reduced
                pivot_rows = new_pivot_rows

        self.rank = max(basis_rank, len(pivot_rows))
        self.dependent_equation_count = max(0, int(self.raw_coded_count) - int(self.rank))
        self.solvable = bool(self.generation_size > 0 and len(known) >= self.generation_size)
        self.decoded_source_symbols = known
        return tuple(sorted(recovered))

    def _reduce_row(
        self,
        row: Gf256EquationRow,
        known: Mapping[int, bytes],
        pivot_rows: Mapping[int, Gf256EquationRow],
    ) -> Optional[Gf256EquationRow]:
        reduced = self._normalize_row(row, known)
        if reduced is None:
            return None
        terms_map = _terms_to_map(reduced.terms)
        rhs = reduced.rhs_payload
        while terms_map:
            pivot = min(terms_map)
            existing = pivot_rows.get(int(pivot))
            if existing is None:
                pivot_coefficient = int(terms_map[pivot])
                if pivot_coefficient != 1:
                    scale = gf256_div(1, pivot_coefficient)
                    terms_map = {
                        index: gf256_mul(coefficient, scale)
                        for index, coefficient in terms_map.items()
                    }
                    rhs = gf256_scale_payload(rhs, scale)
                return Gf256EquationRow(
                    terms=_map_to_terms(terms_map),
                    rhs_payload=rhs,
                )
            factor = int(terms_map[pivot])
            terms_map = _subtract_rows(terms_map, _terms_to_map(existing.terms), factor)
            rhs = gf256_linear_combine(
                [
                    (1, rhs),
                    (factor, existing.rhs_payload),
                ]
            )
            normalized = self._normalize_row(
                Gf256EquationRow(
                    terms=_map_to_terms(terms_map),
                    rhs_payload=rhs,
                ),
                known,
            )
            if normalized is None:
                return None
            terms_map = _terms_to_map(normalized.terms)
            rhs = normalized.rhs_payload
        return Gf256EquationRow(terms=(), rhs_payload=rhs)

    def _normalize_row(
        self,
        row: Gf256EquationRow,
        known: Mapping[int, bytes],
    ) -> Optional[Gf256EquationRow]:
        if not row.terms:
            if _is_zero_payload(row.rhs_payload):
                return None
            return Gf256EquationRow(terms=(), rhs_payload=row.rhs_payload)
        rhs = row.rhs_payload
        unresolved: Dict[int, int] = {}
        known_terms = []
        for source_index, coefficient in row.terms:
            payload = known.get(int(source_index))
            if payload is None:
                unresolved[int(source_index)] = int(coefficient)
            else:
                known_terms.append((int(coefficient), payload))
        if known_terms:
            rhs = gf256_linear_combine([(1, rhs), *known_terms])
        unresolved = {
            index: coefficient
            for index, coefficient in unresolved.items()
            if int(coefficient) != 0
        }
        if not unresolved and _is_zero_payload(rhs):
            return None
        return Gf256EquationRow(
            terms=_map_to_terms(unresolved),
            rhs_payload=rhs,
        )

    def _update_symbol_size(self, payload: bytes, *, strict: bool) -> None:
        if not payload:
            return
        size = len(payload)
        if self.symbol_size <= 0:
            self.symbol_size = size
            return
        if self.symbol_size != size:
            if not strict:
                return
            raise ValueError("symbol_size must stay constant within one generation")

    def _equation_conflicts_with_known(
        self,
        *,
        terms: Tuple[EquationTerm, ...],
        rhs_payload: bytes,
    ) -> str:
        unresolved = []
        known_terms = []
        for source_index, coefficient in terms:
            payload = self.decoded_source_symbols.get(int(source_index))
            if payload is None:
                unresolved.append((int(source_index), int(coefficient)))
            else:
                known_terms.append((int(coefficient), payload))
        normalized_rhs = (
            gf256_linear_combine([(1, rhs_payload), *known_terms]) if known_terms else rhs_payload
        )
        if not unresolved and not _is_zero_payload(normalized_rhs):
            return "equation conflicts with known symbols"
        return ""


def _terms_to_map(terms: Iterable[EquationTerm]) -> Dict[int, int]:
    values: Dict[int, int] = {}
    for source_index, coefficient in terms:
        current = values.get(int(source_index), 0)
        next_value = current ^ int(coefficient)
        if next_value:
            values[int(source_index)] = next_value
        elif int(source_index) in values:
            del values[int(source_index)]
    return values


def _map_to_terms(values: Mapping[int, int]) -> Tuple[EquationTerm, ...]:
    return tuple(
        (int(source_index), int(values[source_index]))
        for source_index in sorted(values)
        if int(values[source_index]) != 0
    )


def _subtract_rows(lhs: Mapping[int, int], rhs: Mapping[int, int], factor: int) -> Dict[int, int]:
    values = dict((int(index), int(coefficient)) for index, coefficient in lhs.items())
    for source_index, coefficient in rhs.items():
        scaled = gf256_mul(int(coefficient), int(factor))
        current = values.get(int(source_index), 0)
        next_value = current ^ scaled
        if next_value:
            values[int(source_index)] = next_value
        elif int(source_index) in values:
            del values[int(source_index)]
    return values


def _is_zero_payload(payload: bytes) -> bool:
    return all(byte == 0 for byte in payload)
