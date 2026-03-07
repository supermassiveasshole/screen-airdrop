from screen_airdrop.sender.controller import build_encoded_frames


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
    items = [first] + [next(gen) for _ in range(4)]

    assert [int(item["chunk_id"]) for item in items[:3]] == [0, 0, 0]
    assert [int(item["chunk_id"]) for item in items[3:5]] == [1, 2]
