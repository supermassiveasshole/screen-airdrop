import pytest

from screen_airdrop.common.information import expand_equation_terms, gf256_linear_combine
from screen_airdrop.common.scheduling import GenerationUnitCandidate, OgrbPolicy, SchedulerContext
from screen_airdrop.sender.information import (
    build_coded_unit,
    build_coded_units,
    build_placeholder_coded_units,
    build_systematic_units,
)
from screen_airdrop.sender.scheduling.ogrb_scheduler import OgrbSkeletonScheduler
from screen_airdrop.sender.scheduling.unit_schedule import (
    BroadcastUnitScheduler,
    CodedAugmentedBroadcastScheduler,
)

pytestmark = pytest.mark.erasure_experiment


def test_broadcast_unit_scheduler_preserves_current_order():
    units = build_systematic_units(
        session_id=42,
        generation_id=0,
        generation_size=3,
        payload_chunks=[b"a", b"b", b"c"],
    )
    scheduler = BroadcastUnitScheduler()

    schedule = scheduler.schedule_units(
        units,
        transport_epoch_id=7,
        realization_count=2,
    )

    assert [getattr(scheduled.unit, "source_index", -1) for scheduled in schedule.units] == [
        1,
        1,
        2,
        2,
        3,
        3,
    ]
    assert [scheduled.realization_index for scheduled in schedule.units] == [0, 1, 0, 1, 0, 1]
    assert all(int(scheduled.transport_epoch_id) == 7 for scheduled in schedule.units)


def test_broadcast_unit_scheduler_defaults_to_one_realization():
    units = build_systematic_units(
        session_id=1,
        generation_id=0,
        generation_size=2,
        payload_chunks=[b"x", b"y"],
    )
    scheduler = BroadcastUnitScheduler()

    schedule = scheduler.schedule_units(units, transport_epoch_id=3)

    assert len(schedule.units) == 2
    assert [getattr(scheduled.unit, "source_index", -1) for scheduled in schedule.units] == [1, 2]
    assert all(int(scheduled.realization_count) == 1 for scheduled in schedule.units)


def test_broadcast_unit_scheduler_supports_multiple_generations_when_called_per_generation():
    units_a = build_systematic_units(
        session_id=1,
        generation_id=0,
        generation_size=2,
        payload_chunks=[b"a", b"b"],
    )
    units_b = build_systematic_units(
        session_id=1,
        generation_id=1,
        generation_size=2,
        payload_chunks=[b"c", b"d"],
    )
    scheduler = BroadcastUnitScheduler()

    schedule_a = scheduler.schedule_units(units_a, transport_epoch_id=0, realization_count=1)
    schedule_b = scheduler.schedule_units(units_b, transport_epoch_id=0, realization_count=1)

    assert [scheduled.unit.generation_id for scheduled in schedule_a.units] == [0, 0]
    assert [scheduled.unit.generation_id for scheduled in schedule_b.units] == [1, 1]


def test_placeholder_coded_builder_creates_valid_coded_units():
    source_units = build_systematic_units(
        session_id=9,
        generation_id=2,
        generation_size=3,
        payload_chunks=[b"a", b"b", b"c"],
    )

    coded_units = build_placeholder_coded_units(
        session_id=9,
        generation_id=2,
        generation_size=3,
        source_units=source_units,
        count=2,
        coding_seed_start=10,
        degree=2,
    )

    assert [unit.equation_id for unit in coded_units] == [0, 1]
    assert [unit.coding_seed for unit in coded_units] == [10, 11]
    assert all(unit.degree == 2 for unit in coded_units)


def test_build_coded_unit_matches_equation_expansion():
    source_units = build_systematic_units(
        session_id=9,
        generation_id=2,
        generation_size=4,
        payload_chunks=[b"\x01", b"\x02", b"\x04", b"\x08"],
    )

    coded_unit = build_coded_unit(
        session_id=9,
        generation_id=2,
        generation_size=4,
        source_units=source_units,
        equation_id=12,
        coding_seed=7,
        degree=3,
    )

    selected_terms = expand_equation_terms(generation_size=4, coding_seed=7, degree=3)
    expected_payload = gf256_linear_combine(
        [(coefficient, source_units[index - 1].payload) for index, coefficient in selected_terms]
    )

    assert coded_unit.payload == expected_payload
    assert coded_unit.coding_scheme.value == "gf256_seed_v2"


def test_build_coded_units_generates_incrementing_equation_ids_and_seeds():
    source_units = build_systematic_units(
        session_id=9,
        generation_id=2,
        generation_size=3,
        payload_chunks=[b"a", b"b", b"c"],
    )

    coded_units = build_coded_units(
        session_id=9,
        generation_id=2,
        generation_size=3,
        source_units=source_units,
        count=3,
        coding_seed_start=20,
        degree=2,
    )

    assert [unit.equation_id for unit in coded_units] == [0, 1, 2]
    assert [unit.coding_seed for unit in coded_units] == [20, 21, 22]


def test_ogrb_skeleton_scheduler_preserves_generation_candidate_order():
    units_a = build_systematic_units(
        session_id=1,
        generation_id=0,
        generation_size=2,
        payload_chunks=[b"a", b"b"],
    )
    units_b = build_systematic_units(
        session_id=1,
        generation_id=1,
        generation_size=2,
        payload_chunks=[b"c", b"d"],
    )
    scheduler = OgrbSkeletonScheduler()

    schedule = scheduler.schedule_units(
        (),
        transport_epoch_id=5,
        generation_candidates=[
            GenerationUnitCandidate(generation_id=0, units=units_a),
            GenerationUnitCandidate(generation_id=1, units=units_b),
        ],
        scheduler_context=SchedulerContext(
            transport_epoch_id=5,
            realization_count=1,
            policy=OgrbPolicy(systematic_budget=2, coded_budget=1),
        ),
    )

    assert [scheduled.unit.generation_id for scheduled in schedule.units] == [0, 0, 1, 1]


def test_coded_augmented_broadcast_scheduler_appends_coded_units_after_systematic():
    systematic_units = build_systematic_units(
        session_id=5,
        generation_id=0,
        generation_size=3,
        payload_chunks=[b"a", b"b", b"c"],
    )
    coded_units = build_coded_units(
        session_id=5,
        generation_id=0,
        generation_size=3,
        source_units=systematic_units,
        count=2,
        coding_seed_start=10,
        degree=3,
    )
    scheduler = CodedAugmentedBroadcastScheduler()

    schedule = scheduler.schedule_generation_units(
        systematic_units=systematic_units,
        coded_units=coded_units,
        transport_epoch_id=4,
        realization_count=1,
    )

    assert [scheduled.unit.unit_type.value for scheduled in schedule.units] == [
        "systematic",
        "systematic",
        "systematic",
        "coded",
        "coded",
    ]
