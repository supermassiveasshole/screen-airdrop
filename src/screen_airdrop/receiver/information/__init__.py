"""Receiver information-layer package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.receiver.information.assembler import ChunkAssembler
    from screen_airdrop.receiver.information.decoder import (
        InformationDecoder,
        IngestResult,
        IngestStatus,
    )
    from screen_airdrop.receiver.information.generation_store import (
        GenerationState,
        GenerationStore,
    )
    from screen_airdrop.receiver.information.solver_state import SolverState
    from screen_airdrop.receiver.information.unit_acceptor import AcceptResult, UnitAcceptor

__all__ = [
    "AcceptResult",
    "ChunkAssembler",
    "GenerationState",
    "GenerationStore",
    "InformationDecoder",
    "IngestResult",
    "IngestStatus",
    "SolverState",
    "UnitAcceptor",
]


def __getattr__(name):
    if name == "ChunkAssembler":
        from screen_airdrop.receiver.information.assembler import ChunkAssembler

        return ChunkAssembler
    if name in {"GenerationState", "GenerationStore"}:
        from screen_airdrop.receiver.information import generation_store as _generation_store

        return getattr(_generation_store, name)
    if name in {"InformationDecoder", "IngestResult", "IngestStatus"}:
        from screen_airdrop.receiver.information import decoder as _decoder

        return getattr(_decoder, name)
    if name == "SolverState":
        from screen_airdrop.receiver.information.solver_state import SolverState

        return SolverState
    if name in {"AcceptResult", "UnitAcceptor"}:
        from screen_airdrop.receiver.information import unit_acceptor as _unit_acceptor

        return getattr(_unit_acceptor, name)
    raise AttributeError(name)
