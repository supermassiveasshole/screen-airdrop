from __future__ import annotations

from screen_airdrop.receiver.cli import _classify_gray4_decode_failure
from screen_airdrop.receiver.pipeline import PipelineStats


def test_classify_gray4_decode_failure_variants() -> None:
    assert _classify_gray4_decode_failure("E2003: bad v3 magic") == "header"
    assert _classify_gray4_decode_failure("E2003: format parity mismatch") == "header"
    assert _classify_gray4_decode_failure("E2004: payload crc mismatch") == "payload"
    assert _classify_gray4_decode_failure("locator new failed: LOW_CONTRAST") == "locator"
    assert _classify_gray4_decode_failure("something else") == "unknown"
    assert _classify_gray4_decode_failure(None) == ""


def test_pipeline_stats_snapshot_exposes_last_failure_fields() -> None:
    stats = PipelineStats(
        last_decode_error="E2003: bad v3 magic",
        last_failure_class="header",
        failure_count_header=2,
        failure_count_payload=1,
        startup_sync_frames_decoded=4,
        startup_control_frames_decoded=3,
        decoded_new_chunks=7,
        decoded_duplicate_chunks=5,
        lock_acquire_to_locked=1,
        lock_locked_to_acquire=2,
        locked_decode_fail_streak_max=3,
    )

    snap = stats.snapshot()

    assert snap["last_decode_error"] == "E2003: bad v3 magic"
    assert snap["last_failure_class"] == "header"
    assert snap["failure_count_header"] == 2
    assert snap["failure_count_payload"] == 1
    assert snap["startup_sync_frames_decoded"] == 4
    assert snap["startup_control_frames_decoded"] == 3
    assert snap["decoded_new_chunks"] == 7
    assert snap["decoded_duplicate_chunks"] == 5
    assert snap["lock_acquire_to_locked"] == 1
    assert snap["lock_locked_to_acquire"] == 2
    assert snap["locked_decode_fail_streak_max"] == 3
