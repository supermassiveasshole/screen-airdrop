from screen_airdrop.sender.information import build_systematic_units
from screen_airdrop.sender.scheduling.unit_schedule import BroadcastUnitScheduler


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

    assert [scheduled.unit.source_index for scheduled in schedule.units] == [1, 1, 2, 2, 3, 3]
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
    assert [scheduled.unit.source_index for scheduled in schedule.units] == [1, 2]
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
