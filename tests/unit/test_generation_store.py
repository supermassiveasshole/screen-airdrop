from screen_airdrop.common.control_plane import CONTROL_KIND_GENERATION, encode_generation_control
from screen_airdrop.common.information import SystematicUnit
from screen_airdrop.receiver.information import (
    AcceptResult,
    ChunkAssembler,
    GenerationStore,
    UnitAcceptor,
)


def _make_unit(*, source_index: int, generation_size: int = 0, payload: bytes = b"x") -> SystematicUnit:
    return SystematicUnit(
        session_id=11,
        generation_id=0,
        generation_size=generation_size,
        source_index=source_index,
        payload_size=len(payload),
        payload=payload,
    )


def test_unit_acceptor_accepts_new_systematic_unit():
    store = GenerationStore()
    acceptor = UnitAcceptor(store)

    result = acceptor.accept(_make_unit(source_index=1), generation_size_hint=2)

    assert result == AcceptResult.ACCEPTED
    state = store.generations[0]
    assert state.generation_size == 2
    assert state.systematic_symbols == {1: b"x"}
    assert state.decode_complete is False


def test_unit_acceptor_deduplicates_systematic_unit_identity():
    store = GenerationStore()
    acceptor = UnitAcceptor(store)

    first = acceptor.accept(_make_unit(source_index=1), generation_size_hint=2)
    second = acceptor.accept(_make_unit(source_index=1), generation_size_hint=2)

    assert first == AcceptResult.ACCEPTED
    assert second == AcceptResult.DUPLICATE
    assert store.generations[0].systematic_symbols == {1: b"x"}


def test_generation_store_marks_complete_when_size_known():
    store = GenerationStore()
    acceptor = UnitAcceptor(store)

    assert acceptor.accept(_make_unit(source_index=1), generation_size_hint=2) == AcceptResult.ACCEPTED
    assert acceptor.accept(_make_unit(source_index=2), generation_size_hint=2) == AcceptResult.ACCEPTED

    state = store.generations[0]
    assert state.generation_size == 2
    assert state.decode_complete is True


def test_generation_store_does_not_exist_before_accept():
    store = GenerationStore()

    assert store.generations == {}


def test_generation_acceptor_keeps_generation_identity_separate():
    store = GenerationStore()
    acceptor = UnitAcceptor(store)

    first = acceptor.accept(_make_unit(source_index=1, generation_size=2), generation_size_hint=2)
    second = acceptor.accept(
        SystematicUnit(
            session_id=11,
            generation_id=1,
            generation_size=2,
            source_index=1,
            payload_size=1,
            payload=b"y",
        ),
        generation_size_hint=2,
    )

    assert first == AcceptResult.ACCEPTED
    assert second == AcceptResult.ACCEPTED
    assert store.generations[0].systematic_symbols == {1: b"x"}
    assert store.generations[1].systematic_symbols == {1: b"y"}


def test_chunk_assembler_binds_placeholder_units_to_active_generation():
    assembler = ChunkAssembler()
    assembler.add_control(
        CONTROL_KIND_GENERATION,
        encode_generation_control(
            {
                "generation_id": 0,
                "generation_size": 2,
                "source_index_base": 1,
                "payload_chunk_count": 2,
                "total_frames": 10,
                "effective_chunk_size": 16,
                "protocol": "basic",
            }
        ),
    )
    assert assembler.add_unit(_make_unit(source_index=1, generation_size=0, payload=b"a")) is True
    assembler.add_control(
        CONTROL_KIND_GENERATION,
        encode_generation_control(
            {
                "generation_id": 1,
                "generation_size": 2,
                "source_index_base": 3,
                "payload_chunk_count": 2,
                "total_frames": 10,
                "effective_chunk_size": 16,
                "protocol": "basic",
            }
        ),
    )
    assert assembler.add_unit(_make_unit(source_index=1, generation_size=0, payload=b"b")) is True

    assert assembler.chunks[1] == b"a"
    assert assembler.chunks[3] == b"b"
