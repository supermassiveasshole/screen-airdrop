from screen_airdrop.common.information import (
    CodedUnit,
    CodedUnitIdentity,
    CodingScheme,
    SystematicUnit,
    SystematicUnitIdentity,
    UnitType,
    coded_unit_identity,
    expand_equation_indices,
    expand_equation_terms,
    gf256_div,
    gf256_inv,
    gf256_linear_combine,
    gf256_mul,
    gf256_scale_payload,
    systematic_unit_identity,
)
from screen_airdrop.common.information.coding import CodingSeedMetadata
from screen_airdrop.sender.information import build_systematic_generation_plans


def test_systematic_unit_construction_roundtrip():
    unit = SystematicUnit(
        session_id=7,
        generation_id=0,
        generation_size=3,
        source_index=2,
        payload_size=5,
        payload=b"hello",
    )

    assert unit.unit_type == UnitType.SYSTEMATIC
    assert unit.session_id == 7
    assert unit.generation_id == 0
    assert unit.generation_size == 3
    assert unit.source_index == 2
    assert unit.payload_size == 5
    assert unit.payload == b"hello"


def test_systematic_unit_identity_helper():
    unit = SystematicUnit(
        session_id=9,
        generation_id=0,
        generation_size=4,
        source_index=3,
        payload_size=3,
        payload=b"abc",
    )

    identity = systematic_unit_identity(unit)

    assert identity == SystematicUnitIdentity(generation_id=0, source_index=3)


def test_coded_unit_construction_roundtrip():
    unit = CodedUnit(
        session_id=7,
        generation_id=2,
        generation_size=5,
        equation_id=11,
        coding_seed=101,
        degree=3,
        payload_size=4,
        payload=b"data",
    )

    assert unit.unit_type == UnitType.CODED
    assert unit.equation_id == 11
    assert unit.coding_seed == 101
    assert unit.degree == 3
    assert unit.coding_scheme == CodingScheme.GF256_SEED_V2


def test_coded_unit_identity_helper():
    unit = CodedUnit(
        session_id=3,
        generation_id=4,
        generation_size=8,
        equation_id=9,
        coding_seed=15,
        degree=2,
        payload_size=2,
        payload=b"xy",
    )

    assert coded_unit_identity(unit) == CodedUnitIdentity(generation_id=4, equation_id=9)


def test_systematic_and_coded_identity_spaces_do_not_overlap():
    systematic = SystematicUnitIdentity(generation_id=1, source_index=3)
    coded = CodedUnitIdentity(generation_id=1, equation_id=3)

    assert systematic != coded


def test_coding_seed_metadata_validates_degree():
    metadata = CodingSeedMetadata(equation_id=1, coding_seed=2, degree=3)
    assert metadata.degree == 3
    assert metadata.coding_scheme == CodingScheme.GF256_SEED_V2


def test_expand_equation_indices_is_deterministic_and_bounded():
    indices_a = expand_equation_indices(generation_size=5, coding_seed=17, degree=3)
    indices_b = expand_equation_indices(generation_size=5, coding_seed=17, degree=3)

    assert indices_a == indices_b
    assert len(indices_a) == 3
    assert all(1 <= value <= 5 for value in indices_a)


def test_expand_equation_terms_are_deterministic_and_non_zero():
    terms_a = expand_equation_terms(generation_size=5, coding_seed=17, degree=3)
    terms_b = expand_equation_terms(generation_size=5, coding_seed=17, degree=3)

    assert terms_a == terms_b
    assert len(terms_a) == 3
    assert all(1 <= source_index <= 5 for source_index, _ in terms_a)
    assert all(1 <= coefficient <= 255 for _, coefficient in terms_a)


def test_expand_equation_terms_supports_explicit_v1_and_v2_schemes():
    terms_v1 = expand_equation_terms(
        generation_size=6,
        coding_seed=1,
        degree=2,
        coding_scheme=CodingScheme.GF256_SEED_V1,
    )
    terms_v2 = expand_equation_terms(
        generation_size=6,
        coding_seed=1,
        degree=2,
        coding_scheme=CodingScheme.GF256_SEED_V2,
    )

    assert terms_v1 != terms_v2
    assert all(1 <= source_index <= 6 for source_index, _ in terms_v1)
    assert all(1 <= source_index <= 6 for source_index, _ in terms_v2)


def test_v2_prefix_coverage_beats_or_matches_v1_for_small_k():
    for generation_size in (4, 6, 8):
        for degree in (2, 3, 4):
            if degree > generation_size:
                continue
            group_count = (generation_size + degree - 1) // degree
            v1_union = {
                source_index
                for seed in range(group_count)
                for source_index, _ in expand_equation_terms(
                    generation_size=generation_size,
                    coding_seed=seed,
                    degree=degree,
                    coding_scheme=CodingScheme.GF256_SEED_V1,
                )
            }
            v2_union = {
                source_index
                for seed in range(group_count)
                for source_index, _ in expand_equation_terms(
                    generation_size=generation_size,
                    coding_seed=seed,
                    degree=degree,
                    coding_scheme=CodingScheme.GF256_SEED_V2,
                )
            }
            assert len(v2_union) >= len(v1_union)


def test_expand_equation_terms_rejects_degree_larger_than_generation_size():
    try:
        expand_equation_terms(generation_size=2, coding_seed=4, degree=9)
    except ValueError as exc:
        assert "degree" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected degree validation error")


def test_gf256_arithmetic_helpers_round_trip():
    coefficient = 87
    value = 19

    product = gf256_mul(coefficient, value)

    assert product != 0
    assert gf256_mul(product, gf256_inv(coefficient)) == value
    assert gf256_div(product, coefficient) == value


def test_gf256_scale_payload_and_linear_combine():
    payload_a = b"\x01\x02"
    payload_b = b"\x03\x04"
    scaled_a = gf256_scale_payload(payload_a, 5)
    scaled_b = gf256_scale_payload(payload_b, 7)

    assert len(scaled_a) == len(payload_a)
    assert len(scaled_b) == len(payload_b)
    assert gf256_linear_combine([(5, payload_a), (7, payload_b)]) == bytes(
        left ^ right for left, right in zip(scaled_a, scaled_b)
    )


def test_systematic_unit_rejects_payload_size_mismatch():
    try:
        SystematicUnit(
            session_id=1,
            generation_id=0,
            generation_size=1,
            source_index=1,
            payload_size=4,
            payload=b"abc",
        )
    except ValueError as exc:
        assert str(exc) == "payload_size must equal len(payload)"
    else:  # pragma: no cover
        raise AssertionError("expected payload_size validation error")


def test_systematic_generation_plans_split_into_multiple_generations():
    plans = build_systematic_generation_plans(
        session_id=5,
        payload_chunks=[b"a", b"b", b"c", b"d", b"e"],
        systematic_generation_size=2,
    )

    assert [plan.generation_id for plan in plans] == [0, 1, 2]
    assert [plan.generation_size for plan in plans] == [2, 2, 1]
    assert [plan.source_index_base for plan in plans] == [1, 3, 5]
    assert [unit.source_index for unit in plans[1].source_units] == [1, 2]
    assert [unit.generation_id for unit in plans[1].source_units] == [1, 1]
