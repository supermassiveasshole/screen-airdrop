from screen_airdrop.common.information import (
    SystematicUnit,
    UnitIdentity,
    UnitType,
    systematic_unit_identity,
)
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

    assert identity == UnitIdentity(generation_id=0, source_index=3)


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
