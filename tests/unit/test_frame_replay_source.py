from screen_airdrop.receiver.frame_replay_source import FrameReplaySource


def test_replay_source_prioritizes_sync_before_epoch_frames():
    source = FrameReplaySource("/tmp/unused")
    names = [
        "epoch_000000_frame_000001.png",
        "sync_000001.png",
        "epoch_000000_frame_000000.png",
        "sync_000000.png",
    ]

    ordered = sorted(names, key=source._sort_key)

    assert ordered == [
        "sync_000000.png",
        "sync_000001.png",
        "epoch_000000_frame_000000.png",
        "epoch_000000_frame_000001.png",
    ]
