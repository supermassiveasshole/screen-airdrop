# pyright: reportIndexIssue=false
from __future__ import annotations

from screen_airdrop.receiver.cli import _classify_gray4_decode_failure
from screen_airdrop.receiver.runtime.stats import ScreenLiveRuntimeStats
from screen_airdrop.receiver.protocol_observability import LayeredReportAdapter


def test_classify_gray4_decode_failure_variants() -> None:
    assert _classify_gray4_decode_failure("E2003: bad v3 magic") == "header"
    assert _classify_gray4_decode_failure("E2003: format parity mismatch") == "header"
    assert _classify_gray4_decode_failure("E2004: payload crc mismatch") == "payload"
    assert _classify_gray4_decode_failure("locator new failed: LOW_CONTRAST") == "locator"
    assert _classify_gray4_decode_failure("something else") == "unknown"
    assert _classify_gray4_decode_failure(None) == ""


def test_pipeline_stats_snapshot_exposes_last_failure_fields() -> None:
    """Test that ScreenLiveRuntimeStats snapshot includes protocol adapter fields."""
    # Create stats with layered protocol
    stats = ScreenLiveRuntimeStats(protocol="layered")

    # Set protocol adapter to LayeredReportAdapter
    stats.protocol_report_adapter = LayeredReportAdapter()

    # Set basic stats fields
    stats.last_decode_error = "E2003: bad v3 magic"
    stats.last_failure_class = "header"
    stats.failure_count_header = 2
    stats.failure_count_payload = 1
    stats.startup_sync_frames_decoded = 4
    stats.startup_control_frames_decoded = 3
    stats.decoded_new_chunks = 7
    stats.decoded_duplicate_chunks = 5
    stats.lock_acquire_to_locked = 1
    stats.lock_locked_to_acquire = 2
    stats.locked_decode_fail_streak_max = 3

    # Set protocol adapter fields
    adapter = stats.protocol_report_adapter
    assert isinstance(adapter, LayeredReportAdapter)
    adapter.bootstrap_rs_fail_count = 4
    adapter.bootstrap_crc_fail_count = 5
    adapter.body_rs_fail_count = 6
    adapter.body_crc_fail_count = 7
    adapter.bootstrap_attempt_count = 10
    adapter.bootstrap_threshold_sum = 260.0
    adapter.bootstrap_threshold_count = 2
    adapter.bootstrap_vote_margin_sum = 5.0
    adapter.bootstrap_vote_margin_count = 2
    adapter.bootstrap_vote_margin_min = 1.0
    adapter.bootstrap_bit_fail_counts = [1] + [0] * 79
    adapter.bootstrap_fail_examples = [{"mask_id_guess": 3}]

    snap = stats.snapshot()

    # Verify basic stats fields
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

    # Verify protocol adapter fields are included in snapshot
    assert snap["layered_bootstrap_rs_fail_count"] == 4.0
    assert snap["layered_bootstrap_crc_fail_count"] == 5.0
    assert snap["layered_body_rs_fail_count"] == 6.0
    assert snap["layered_body_crc_fail_count"] == 7.0
    assert snap["layered_bootstrap_attempt_count"] == 10.0
    assert snap["layered_bootstrap_threshold_avg"] == 130.0  # 260.0 / 2
    assert snap["layered_bootstrap_vote_margin_min"] == 1.0
    assert snap["layered_bootstrap_vote_margin_avg"] == 2.5  # 5.0 / 2
    assert snap["layered_bootstrap_bit_fail_counts"][0] == 1
    assert snap["layered_bootstrap_fail_examples"] == [{"mask_id_guess": 3}]

    # Verify hardcoded fields
    assert snap["layered_format_fail_count"] == 0.0
