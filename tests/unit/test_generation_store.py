import pytest

from screen_airdrop.common.control_plane import CONTROL_KIND_GENERATION, encode_generation_control
from screen_airdrop.common.information import (
    CodedUnit,
    CodingScheme,
    SystematicUnit,
    expand_equation_terms,
    gf256_scale_payload,
)
from screen_airdrop.receiver.information import (
    AcceptResult,
    ChunkAssembler,
    GenerationStore,
    InformationDecoder,
    IngestStatus,
    UnitAcceptor,
)
from screen_airdrop.sender.information import build_coded_unit, build_systematic_units

pytestmark = pytest.mark.erasure_experiment


def _make_unit(*, source_index: int, generation_size: int = 0, payload: bytes = b"x") -> SystematicUnit:
    return SystematicUnit(
        session_id=11,
        generation_id=0,
        generation_size=generation_size,
        source_index=source_index,
        payload_size=len(payload),
        payload=payload,
    )


def _make_coded_unit(
    *,
    equation_id: int,
    generation_id: int = 0,
    generation_size: int = 0,
    payload: bytes = b"z",
) -> CodedUnit:
    return CodedUnit(
        session_id=11,
        generation_id=generation_id,
        generation_size=generation_size,
        equation_id=equation_id,
        coding_seed=equation_id + 100,
        degree=2,
        payload_size=len(payload),
        payload=payload,
    )


def test_unit_acceptor_accepts_new_systematic_unit():
    store = GenerationStore()
    acceptor = UnitAcceptor(store)

    result = acceptor.accept(_make_unit(source_index=1), generation_size_hint=2)

    assert result == AcceptResult.ACCEPTED_SYSTEMATIC
    state = store.generations[0]
    assert state.generation_size == 2
    assert state.systematic_symbols == {1: b"x"}
    assert state.decode_complete is False


def test_unit_acceptor_deduplicates_systematic_unit_identity():
    store = GenerationStore()
    acceptor = UnitAcceptor(store)

    first = acceptor.accept(_make_unit(source_index=1), generation_size_hint=2)
    second = acceptor.accept(_make_unit(source_index=1), generation_size_hint=2)

    assert first == AcceptResult.ACCEPTED_SYSTEMATIC
    assert second == AcceptResult.DUPLICATE
    assert store.generations[0].systematic_symbols == {1: b"x"}


def test_generation_store_marks_complete_when_size_known():
    store = GenerationStore()
    acceptor = UnitAcceptor(store)

    assert (
        acceptor.accept(_make_unit(source_index=1), generation_size_hint=2)
        == AcceptResult.ACCEPTED_SYSTEMATIC
    )
    assert (
        acceptor.accept(_make_unit(source_index=2), generation_size_hint=2)
        == AcceptResult.ACCEPTED_SYSTEMATIC
    )

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

    assert first == AcceptResult.ACCEPTED_SYSTEMATIC
    assert second == AcceptResult.ACCEPTED_SYSTEMATIC
    assert store.generations[0].systematic_symbols == {1: b"x"}
    assert store.generations[1].systematic_symbols == {1: b"y"}


def test_unit_acceptor_accepts_new_coded_unit():
    store = GenerationStore()
    acceptor = UnitAcceptor(store)

    result = acceptor.accept(_make_coded_unit(equation_id=7), generation_size_hint=4)

    assert result == AcceptResult.ACCEPTED_CODED
    state = store.generations[0]
    assert list(state.coded_equations) == [7]
    assert state.solver_rank == 0
    assert state.decode_complete is False


def test_unit_acceptor_deduplicates_coded_equations():
    store = GenerationStore()
    acceptor = UnitAcceptor(store)

    first = acceptor.accept(_make_coded_unit(equation_id=3), generation_size_hint=4)
    second = acceptor.accept(_make_coded_unit(equation_id=3), generation_size_hint=4)

    assert first == AcceptResult.ACCEPTED_CODED
    assert second == AcceptResult.DUPLICATE
    assert list(store.generations[0].coded_equations) == [3]
    assert int(store.generations[0].duplicate_equation_count) == 1


def test_information_decoder_records_coded_arrival_without_marking_complete():
    store = GenerationStore()
    decoder = InformationDecoder(store)

    result = decoder.ingest(_make_coded_unit(equation_id=1), generation_size_hint=2)

    assert result.status == IngestStatus.ACCEPTED_CODED
    assert result.rank_increased is True
    assert result.dependent_equation is False
    state = store.generations[0]
    assert state.decode_complete is False
    assert state.decoded_payload_ready is False
    assert state.coded_equation_count == 1


def test_information_decoder_recovers_single_missing_symbol_from_one_coded_equation():
    store = GenerationStore()
    decoder = InformationDecoder(store)

    source_units = build_systematic_units(
        session_id=11,
        generation_id=0,
        generation_size=3,
        payload_chunks=[b"a", b"b", b"c"],
    )
    assert (
        decoder.ingest(source_units[0], generation_size_hint=3).status
        == IngestStatus.ACCEPTED_SYSTEMATIC
    )
    assert (
        decoder.ingest(source_units[1], generation_size_hint=3).status
        == IngestStatus.ACCEPTED_SYSTEMATIC
    )

    coded_unit = build_coded_unit(
        session_id=11,
        generation_id=0,
        generation_size=3,
        source_units=source_units,
        equation_id=5,
        coding_seed=5,
        degree=3,
    )

    result = decoder.ingest(coded_unit, generation_size_hint=3)

    assert result.status == IngestStatus.GENERATION_COMPLETE
    assert result.recovered_source_symbols == {3: b"c"}
    state = store.generations[0]
    assert state.decode_complete is True
    assert state.solver_rank >= 1
    assert state.recovered_source_count == 3


def test_information_decoder_recovers_multiple_symbols_from_independent_equations():
    store = GenerationStore()
    decoder = InformationDecoder(store)

    generation_size = 4
    payloads = [bytes([value]) for value in (1, 2, 3, 4)]
    source_units = build_systematic_units(
        session_id=11,
        generation_id=0,
        generation_size=generation_size,
        payload_chunks=payloads,
    )
    assert (
        decoder.ingest(source_units[0], generation_size_hint=generation_size).status
        == IngestStatus.ACCEPTED_SYSTEMATIC
    )
    coded_units = [
        build_coded_unit(
            session_id=11,
            generation_id=0,
            generation_size=generation_size,
            source_units=source_units,
            equation_id=seed,
            coding_seed=seed,
            degree=2,
        )
        for seed in range(4)
    ]

    final_result = None
    for unit in coded_units:
        final_result = decoder.ingest(unit, generation_size_hint=generation_size)
        if final_result.generation_complete:
            break

    assert final_result is not None
    assert final_result.generation_complete is True
    state = store.generations[0]
    assert state.decode_complete is True
    assert state.recovered_source_symbols == {1: b"\x01", 2: b"\x02", 3: b"\x03", 4: b"\x04"}


def test_information_decoder_keeps_generation_incomplete_when_equations_insufficient():
    store = GenerationStore()
    decoder = InformationDecoder(store)

    source_units = build_systematic_units(
        session_id=11,
        generation_id=0,
        generation_size=4,
        payload_chunks=[b"a", b"b", b"c", b"d"],
    )
    assert (
        decoder.ingest(source_units[0], generation_size_hint=4).status
        == IngestStatus.ACCEPTED_SYSTEMATIC
    )
    coded = build_coded_unit(
        session_id=11,
        generation_id=0,
        generation_size=4,
        source_units=source_units,
        equation_id=0,
        coding_seed=1,
        degree=2,
    )

    result = decoder.ingest(coded, generation_size_hint=4)

    assert result.status == IngestStatus.ACCEPTED_CODED
    assert result.recovered_source_symbols == {}
    assert result.rank_increased is True
    assert result.dependent_equation is False
    state = store.generations[0]
    assert state.decode_complete is False
    assert state.solver_rank >= 1
    assert state.recovered_source_count == 1


def test_information_decoder_marks_algebraically_dependent_equation_without_recovery():
    store = GenerationStore()
    decoder = InformationDecoder(store)

    source_units = build_systematic_units(
        session_id=11,
        generation_id=0,
        generation_size=4,
        payload_chunks=[b"a", b"b", b"c", b"d"],
    )
    first = build_coded_unit(
        session_id=11,
        generation_id=0,
        generation_size=4,
        source_units=source_units,
        equation_id=0,
        coding_seed=7,
        degree=2,
    )
    dependent = build_coded_unit(
        session_id=11,
        generation_id=0,
        generation_size=4,
        source_units=source_units,
        equation_id=1,
        coding_seed=7,
        degree=2,
    )

    first_result = decoder.ingest(first, generation_size_hint=4)
    dependent_result = decoder.ingest(dependent, generation_size_hint=4)

    assert first_result.status == IngestStatus.ACCEPTED_CODED
    assert first_result.rank_increased is True
    assert dependent_result.status == IngestStatus.ACCEPTED_CODED
    assert dependent_result.rank_increased is False
    assert dependent_result.dependent_equation is True
    state = store.generations[0]
    assert state.coded_equation_count == 2
    assert state.dependent_equation_count >= 1
    assert state.solver_rank == 1


def test_information_decoder_recovers_three_missing_symbols_in_small_generation():
    store = GenerationStore()
    decoder = InformationDecoder(store)

    generation_size = 4
    payloads = [bytes([value]) for value in (10, 20, 30, 40)]
    source_units = build_systematic_units(
        session_id=11,
        generation_id=0,
        generation_size=generation_size,
        payload_chunks=payloads,
    )
    assert (
        decoder.ingest(source_units[0], generation_size_hint=generation_size).status
        == IngestStatus.ACCEPTED_SYSTEMATIC
    )

    final_result = None
    for seed in range(4):
        final_result = decoder.ingest(
            build_coded_unit(
                session_id=11,
                generation_id=0,
                generation_size=generation_size,
                source_units=source_units,
                equation_id=seed,
                coding_seed=seed,
                degree=2,
            ),
            generation_size_hint=generation_size,
        )
        if final_result.generation_complete:
            break

    assert final_result is not None
    assert final_result.generation_complete is True
    state = store.generations[0]
    assert state.decode_complete is True
    assert state.solver_rank >= 1
    assert state.recovered_source_count >= 3
    assert state.recovered_source_symbols == {
        1: b"\x0a",
        2: b"\x14",
        3: b"\x1e",
        4: b"\x28",
    }


def test_information_decoder_marks_invalid_coded_equation():
    store = GenerationStore()
    decoder = InformationDecoder(store)
    invalid = _make_coded_unit(equation_id=7, generation_size=0, payload=b"x")

    result = decoder.ingest(invalid, generation_size_hint=0)

    assert result.status == IngestStatus.INVALID_CODED
    state = store.generations[0]
    assert state.invalid_equation_count >= 1


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


def test_chunk_assembler_materializes_recovered_symbols_into_global_chunk_ids():
    assembler = ChunkAssembler()
    assembler.add_control(
        CONTROL_KIND_GENERATION,
        encode_generation_control(
            {
                "generation_id": 0,
                "generation_size": 3,
                "source_index_base": 5,
                "payload_chunk_count": 3,
                "coded_payload_envelope": "gf256_seed_v2",
                "coded_redundancy_count": 1,
                "coded_degree": 3,
                "total_frames": 10,
                "effective_chunk_size": 16,
                "protocol": "basic",
            }
        ),
    )
    source_units = build_systematic_units(
        session_id=11,
        generation_id=0,
        generation_size=3,
        payload_chunks=[b"a", b"b", b"c"],
    )
    assert assembler.add_unit(source_units[0]) is True
    assert assembler.add_unit(source_units[1]) is True

    coded_unit = build_coded_unit(
        session_id=11,
        generation_id=0,
        generation_size=3,
        source_units=source_units,
        equation_id=9,
        coding_seed=9,
        degree=3,
    )

    assert assembler.add_unit(coded_unit) is True
    assert assembler.chunks[5] == b"a"
    assert assembler.chunks[6] == b"b"
    assert assembler.chunks[7] == b"c"


def test_information_decoder_marks_conflicting_coded_equation():
    store = GenerationStore()
    decoder = InformationDecoder(store)
    source_units = build_systematic_units(
        session_id=11,
        generation_id=0,
        generation_size=2,
        payload_chunks=[b"a", b"b"],
    )
    decoder.ingest(source_units[0], generation_size_hint=2)
    decoder.ingest(source_units[1], generation_size_hint=2)
    conflicting = CodedUnit(
        session_id=11,
        generation_id=0,
        generation_size=2,
        equation_id=99,
        coding_seed=0,
        degree=1,
        coding_scheme=CodingScheme.GF256_SEED_V1,
        payload_size=1,
        payload=b"\xff",
    )

    term = expand_equation_terms(generation_size=2, coding_seed=0, degree=1)[0]
    expected_payload = gf256_scale_payload(source_units[term[0] - 1].payload, term[1])
    assert conflicting.payload != expected_payload

    result = decoder.ingest(conflicting, generation_size_hint=2)

    assert result.status == IngestStatus.CONFLICTING_CODED
    assert result.generation_complete is True
    state = store.generations[0]
    assert state.conflict_count >= 1


def test_information_decoder_duplicate_coded_equation_does_not_inflate_rank():
    store = GenerationStore()
    decoder = InformationDecoder(store)
    unit = _make_coded_unit(equation_id=5, generation_size=4, payload=b"x")

    first = decoder.ingest(unit, generation_size_hint=4)
    second = decoder.ingest(unit, generation_size_hint=4)

    assert first.status == IngestStatus.ACCEPTED_CODED
    assert second.status == IngestStatus.DUPLICATE
    state = store.generations[0]
    assert state.coded_equation_count == 1
    assert state.duplicate_equation_count == 1
    assert state.solver_rank <= 1


def test_chunk_assembler_rejects_coded_unit_without_generation_coded_context():
    assembler = ChunkAssembler()
    assembler.add_control(
        CONTROL_KIND_GENERATION,
        encode_generation_control(
            {
                "generation_id": 0,
                "generation_size": 3,
                "source_index_base": 1,
                "payload_chunk_count": 3,
                "total_frames": 10,
                "effective_chunk_size": 16,
                "protocol": "basic",
            }
        ),
    )
    source_units = build_systematic_units(
        session_id=11,
        generation_id=0,
        generation_size=3,
        payload_chunks=[b"a", b"b", b"c"],
    )
    coded_unit = build_coded_unit(
        session_id=11,
        generation_id=0,
        generation_size=3,
        source_units=source_units,
        equation_id=1,
        coding_seed=1,
        degree=3,
    )

    assert assembler.add_unit(coded_unit) is False
    state = assembler.generation_store.generations[0]
    assert state.invalid_equation_count >= 1
