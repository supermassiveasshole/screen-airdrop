from screen_airdrop.sender.application.controller import build_encoded_frames
from screen_airdrop.sender.scheduling.broadcast_schedule import BroadcastSchedule
from screen_airdrop.sender.transport.gray4.encoder import frame_capacity_bytes_gray4


def test_epochs_zero_means_infinite_loop(tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text("hello sender epochs", encoding="utf-8")

    gen = build_encoded_frames(
        input_path=str(sample),
        protocol="basic",
        compress="none",
        sync_frames=0,
        epochs=0,
    )

    first = next(gen)
    items = [first] + [next(gen) for _ in range(63)]

    # We should see at least one frame from epoch 1, proving the generator
    # continues past the first epoch when epochs=0.
    assert any(int(item["epoch"]) >= 1 for item in items)


def test_manifest_is_repeated_at_start_of_each_epoch(tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text("hello manifest repeat", encoding="utf-8")

    gen = build_encoded_frames(
        input_path=str(sample),
        protocol="basic",
        compress="none",
        sync_frames=0,
        manifest_repeat=3,
        epochs=1,
    )

    first = next(gen)
    items = [first] + [next(gen) for _ in range(12)]

    assert [int(item["chunk_id"]) for item in items[:3]] == [0, 0, 0]
    assert [item["control_kind"] for item in items[:3]] == ["manifest", "manifest", "manifest"]
    assert [int(item["chunk_id"]) for item in items[3:6]] == [0xFFFFFFFD, 0xFFFFFFFD, 0xFFFFFFFD]
    assert [item["control_kind"] for item in items[3:6]] == ["session", "session", "session"]
    assert [int(item["chunk_id"]) for item in items[6:9]] == [0xFFFFFFFE, 0xFFFFFFFE, 0xFFFFFFFE]
    assert [item["control_kind"] for item in items[6:9]] == ["layout", "layout", "layout"]
    assert [int(item["chunk_id"]) for item in items[9:12]] == [0xFFFFFFFC, 0xFFFFFFFC, 0xFFFFFFFC]
    assert [item["control_family"] for item in items[9:12]] == ["generation", "generation", "generation"]
    assert [item["control_kind"] for item in items[9:12]] == ["generation", "generation", "generation"]
    assert int(items[12]["chunk_id"]) == 1


def test_schedule_policy_controls_epoch_bootstrap_repeat(tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text("hello schedule policy", encoding="utf-8")

    gen = build_encoded_frames(
        input_path=str(sample),
        protocol="basic",
        compress="none",
        sync_frames=0,
        manifest_repeat=1,
        schedule=BroadcastSchedule(sync_frames=2, control_burst_repeat=4),
        epochs=1,
    )

    items = [next(gen) for _ in range(18)]

    assert [item["kind"] for item in items[:2]] == ["sync", "sync"]
    assert [int(item["chunk_id"]) for item in items[2:6]] == [0, 0, 0, 0]
    assert [item["plane"] for item in items[2:6]] == ["control", "control", "control", "control"]
    assert [item["control_family"] for item in items[2:6]] == ["bootstrap"] * 4
    assert [item["control_kind"] for item in items[2:6]] == ["manifest"] * 4
    assert [int(item["chunk_id"]) for item in items[6:10]] == [0xFFFFFFFD] * 4
    assert [item["control_kind"] for item in items[6:10]] == ["session"] * 4
    assert [int(item["chunk_id"]) for item in items[10:14]] == [0xFFFFFFFE] * 4
    assert [item["control_kind"] for item in items[10:14]] == ["layout"] * 4
    assert [int(item["chunk_id"]) for item in items[14:18]] == [0xFFFFFFFC] * 4
    assert [item["control_kind"] for item in items[14:18]] == ["generation"] * 4


def test_control_plane_metadata_is_explicit(tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text("hello control plane", encoding="utf-8")

    first = next(
        build_encoded_frames(
            input_path=str(sample),
            protocol="basic",
            compress="none",
            sync_frames=0,
            epochs=1,
        )
    )

    control_plane = list(first["metadata"]["control_plane"])
    assert len(control_plane) == 4
    assert control_plane[0]["family"] == "bootstrap"
    assert control_plane[0]["kind"] == "manifest"
    assert control_plane[0]["wire_chunk_id"] == 0
    assert int(control_plane[0]["payload_size"]) > 0
    assert control_plane[1]["family"] == "bootstrap"
    assert control_plane[1]["kind"] == "session"
    assert control_plane[1]["wire_chunk_id"] == 0xFFFFFFFD
    assert int(control_plane[1]["payload_size"]) > 0
    assert control_plane[2]["family"] == "bootstrap"
    assert control_plane[2]["kind"] == "layout"
    assert control_plane[2]["wire_chunk_id"] == 0xFFFFFFFE
    assert int(control_plane[2]["payload_size"]) > 0
    assert control_plane[3]["family"] == "generation"
    assert control_plane[3]["kind"] == "generation"
    assert control_plane[3]["wire_chunk_id"] == 0xFFFFFFFC
    assert int(control_plane[3]["payload_size"]) > 0


def test_schedule_policy_can_repeat_data_chunks_with_realizations(tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text("hello data realizations", encoding="utf-8")

    gen = build_encoded_frames(
        input_path=str(sample),
        protocol="basic",
        compress="none",
        sync_frames=0,
        schedule=BroadcastSchedule(sync_frames=0, control_burst_repeat=1, data_realizations=2),
        epochs=1,
    )

    first = next(gen)
    items = [first] + [next(gen) for _ in range(9)]
    data_items = [item for item in items if item["kind"] == "data" and item.get("plane") == "data"]

    assert int(first["metadata"]["schedule"]["data_realizations"]) == 2
    assert int(first["metadata"]["payload_chunk_count"]) >= 1
    assert int(first["metadata"]["payload_frame_count"]) == int(
        first["metadata"]["payload_chunk_count"]
    ) * 2
    assert len(data_items) >= 2
    assert int(data_items[0]["chunk_id"]) == int(data_items[1]["chunk_id"]) == 1
    assert int(data_items[0]["realization_index"]) == 0
    assert int(data_items[1]["realization_index"]) == 1
    assert int(data_items[0]["realization_count"]) == 2
    assert int(data_items[1]["realization_count"]) == 2
    assert int(data_items[0]["frame_id"]) != int(data_items[1]["frame_id"])
    assert int(data_items[0]["generation_id"]) == 0
    assert int(data_items[1]["generation_id"]) == 0
    assert int(data_items[0]["generation_size"]) == int(first["metadata"]["payload_chunk_count"])
    assert data_items[0]["transmission_unit"].source_index == 1
    assert data_items[0]["transmission_unit"].generation_id == 0
    assert data_items[0]["transmission_unit"].generation_size == int(
        first["metadata"]["payload_chunk_count"]
    )


def test_sender_splits_payload_into_multiple_generations(tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text("abcdefghij" * 400, encoding="utf-8")

    gen = build_encoded_frames(
        input_path=str(sample),
        protocol="basic",
        compress="none",
        sync_frames=0,
        chunk_size=256,
        systematic_generation_size=3,
        epochs=1,
    )

    items = [next(gen) for _ in range(24)]
    first = items[0]
    generation_controls = [
        item for item in items if item.get("control_kind") == "generation"
    ]
    data_items = [item for item in items if item.get("plane") == "data"]
    generation_ids = []
    for item in generation_controls:
        generation_id = int(item["generation_id"])
        if generation_id not in generation_ids:
            generation_ids.append(generation_id)

    assert int(first["metadata"]["systematic_generation_count"]) >= 2
    assert len(first["metadata"]["systematic_generations"]) == int(
        first["metadata"]["systematic_generation_count"]
    )
    assert len(generation_controls) >= 2
    assert generation_ids[:2] == [0, 1]
    assert int(data_items[0]["chunk_id"]) == 1
    assert int(data_items[0]["global_chunk_id"]) == 1
    assert int(data_items[0]["generation_id"]) == 0


def test_chunk_fill_ratio_can_use_full_frame_capacity(tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text("hello chunk fill ratio", encoding="utf-8")

    first = next(
        build_encoded_frames(
            input_path=str(sample),
            protocol="gray4",
            compress="none",
            sync_frames=0,
            chunk_size=999999,
            chunk_fill_ratio=1.0,
            module_grid="224x136",
            ecc_level="L",
            epochs=1,
        )
    )

    expected = frame_capacity_bytes_gray4(grid_w=224, grid_h=136, ecc_level="L")
    assert int(first["metadata"]["frame_payload_cap"]) == expected
    assert int(first["metadata"]["effective_chunk_size"]) == expected


def test_chunk_fill_ratio_drives_effective_chunk_size_when_unspecified(tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text("hello ratio only", encoding="utf-8")

    first = next(
        build_encoded_frames(
            input_path=str(sample),
            protocol="gray4",
            compress="none",
            sync_frames=0,
            chunk_size=None,
            chunk_fill_ratio=1.0,
            module_grid="100x60",
            ecc_level="L",
            epochs=1,
        )
    )

    assert int(first["metadata"]["chunk_size"]) == int(first["metadata"]["effective_chunk_size"])
    assert int(first["metadata"]["effective_chunk_size"]) == int(first["metadata"]["frame_payload_cap"])


def test_layered_metadata_exposes_profiles(tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text("hello layered metadata", encoding="utf-8")

    first = next(
        build_encoded_frames(
            input_path=str(sample),
            protocol="layered",
            compress="none",
            sync_frames=0,
            chunk_fill_ratio=1.0,
            module_grid="224x136",
            epochs=1,
        )
    )

    metadata = dict(first["metadata"])
    assert int(metadata["bootstrap_profile_id"]) == 2
    assert int(metadata["bootstrap_ecc_profile_id"]) == 2
    assert int(metadata["body_profile_id"]) == 4
    assert str(metadata["body_profile_name"]) == "robust"
    assert int(metadata["body_ecc_profile_id"]) == 4

    control_layout = next(
        item for item in metadata["control_plane"] if item["kind"] == "layout"
    )
    assert int(control_layout["payload_size"]) > 0


def test_layered_sender_normalizes_session_identity_to_16bit(tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text("hello layered session identity", encoding="utf-8")

    first = next(
        build_encoded_frames(
            input_path=str(sample),
            protocol="layered",
            compress="none",
            sync_frames=0,
            chunk_fill_ratio=1.0,
            module_grid="224x136",
            session_id=0x12345678,
            epochs=1,
        )
    )

    metadata = dict(first["metadata"])
    assert int(metadata["session_id"]) == 0x5678
