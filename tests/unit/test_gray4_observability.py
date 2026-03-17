# pyright: reportIndexIssue=false
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
        layered_format_fail_count=3,
        layered_bootstrap_rs_fail_count=4,
        layered_bootstrap_crc_fail_count=5,
        layered_body_rs_fail_count=6,
        layered_body_crc_fail_count=7,
        layered_bootstrap_threshold_fallback_attempts=8,
        layered_bootstrap_threshold_fallback_successes=9,
        layered_format_attempt_count=10,
        layered_format_fallback_attempts=11,
        layered_format_fallback_successes=12,
        layered_format_primary_threshold_sum=260.0,
        layered_format_primary_threshold_count=2,
        layered_format_fallback_threshold_sum=390.0,
        layered_format_fallback_threshold_count=3,
        layered_format_vote_margin_sum=5.0,
        layered_format_vote_margin_count=2,
        layered_format_vote_margin_min=1.0,
        layered_format_mask_fail_counts={"3": 2},
        layered_format_bit_fail_counts=[1] + [0] * 79,
        layered_format_line_fail_horizontal=4,
        layered_format_line_fail_vertical=5,
        layered_format_fail_examples=[{"mask_id_guess": 3}],
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
    assert snap["layered_format_fail_count"] == 3
    assert snap["layered_bootstrap_rs_fail_count"] == 4
    assert snap["layered_bootstrap_crc_fail_count"] == 5
    assert snap["layered_body_rs_fail_count"] == 6
    assert snap["layered_body_crc_fail_count"] == 7
    assert snap["layered_bootstrap_threshold_fallback_attempts"] == 8
    assert snap["layered_bootstrap_threshold_fallback_successes"] == 9
    assert snap["layered_format_attempt_count"] == 10
    assert snap["layered_format_fallback_attempts"] == 11
    assert snap["layered_format_fallback_successes"] == 12
    assert snap["layered_format_primary_threshold_avg"] == 130.0
    assert snap["layered_format_fallback_threshold_avg"] == 130.0
    assert snap["layered_format_vote_margin_min"] == 1.0
    assert snap["layered_format_vote_margin_avg"] == 2.5
    assert snap["layered_format_mask_fail_counts"] == {"3": 2}
    assert snap["layered_format_bit_fail_counts"][0] == 1
    assert snap["layered_format_line_fail_counts"] == {"horizontal": 4, "vertical": 5}
    assert snap["layered_format_fail_examples"] == [{"mask_id_guess": 3}]
    assert snap["startup_sync_frames_decoded"] == 4
    assert snap["startup_control_frames_decoded"] == 3
    assert snap["decoded_new_chunks"] == 7
    assert snap["decoded_duplicate_chunks"] == 5
    assert snap["lock_acquire_to_locked"] == 1
    assert snap["lock_locked_to_acquire"] == 2
    assert snap["locked_decode_fail_streak_max"] == 3
