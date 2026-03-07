from screen_airdrop.receiver.stats import TransferStats


def test_stats_snapshot_and_finalize():
    s = TransferStats(start_ts=100.0)
    s.on_frame(decoded_ok=False, payload_len=0, ts=101.0)
    s.on_frame(decoded_ok=True, payload_len=200, ts=102.0)
    s.on_frame(decoded_ok=True, payload_len=300, ts=103.0)

    snap = s.snapshot(ts=104.0)
    assert snap["raw_frame_rate_fps"] > 0
    assert snap["valid_frame_rate_fps"] > 0
    assert snap["goodput_kbps"] > 0
    assert snap["bad_frame_rate"] > 0

    final = s.finalize(output_size_bytes=500, ts=105.0)
    assert final["end_to_end_kbps"] > 0
    assert final["recovery_latency_s"] > 0
