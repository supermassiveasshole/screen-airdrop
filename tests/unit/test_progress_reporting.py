"""Tests for progress reporting system."""

from screen_airdrop.receiver.reporting.console import ConsoleProgressReporter
from screen_airdrop.receiver.reporting.formatters import (
    CompactStatsFormatter,
    ScreenLiveStatsFormatter,
)
from screen_airdrop.receiver.reporting.reporter import SilentProgressReporter


def test_screen_live_formatter_basic():
    """Test ScreenLiveStatsFormatter with basic snapshot."""
    formatter = ScreenLiveStatsFormatter()
    snapshot = {
        "captured": 100,
        "decode_ok": 50,
        "assembled": 48,
        "duplicate_frames": 30,
        "dropped_queue_full": 1,
        "dropped_slot_unavailable": 2,
        "dropped_slot_starvation": 5,
        "decode_queue_depth": 3,
        "capture_overwrite_count": 0,
        "prep_backlog": 0,
        "assembled_bytes": 50000,
    }

    line = formatter.format_progress_line(snapshot, missing_count=10)

    assert "captured=100" in line
    assert "decoded=50" in line
    assert "assembled=48" in line
    assert "missing=10" in line
    assert "dropped=8(q=1 slot=2 starve=5)" in line
    assert "dedup=30" in line


def test_screen_live_formatter_with_delta():
    """Test ScreenLiveStatsFormatter with delta calculations."""
    formatter = ScreenLiveStatsFormatter()

    snapshot_prev = {
        "captured": 100,
        "decode_ok": 50,
        "assembled": 48,
        "assembled_bytes": 50000,
        "raw_grab_frames": 120,
        "prep_processed_frames": 110,
        "accepted_for_decode_frames": 70,
    }

    snapshot_now = {
        "captured": 150,
        "decode_ok": 75,
        "assembled": 73,
        "assembled_bytes": 75000,
        "raw_grab_frames": 170,
        "prep_processed_frames": 160,
        "accepted_for_decode_frames": 95,
        "duplicate_frames": 30,
        "dropped_queue_full": 1,
        "dropped_slot_unavailable": 2,
        "dropped_slot_starvation": 5,
        "decode_queue_depth": 3,
        "capture_overwrite_count": 0,
        "prep_backlog": 0,
    }

    line = formatter.format_progress_line(
        snapshot_now,
        missing_count=10,
        delta_snapshot=snapshot_prev,
        delta_seconds=1.0,
    )

    # Check FPS calculations (delta / time)
    assert "cap_fps=50.00" in line  # (150-100)/1.0
    assert "dec_fps=25.00" in line  # (75-50)/1.0
    assert "rx_KBps=24.41" in line  # (75000-50000)/1024/1.0


def test_screen_live_formatter_timing_metrics():
    """Test ScreenLiveStatsFormatter timing calculations."""
    formatter = ScreenLiveStatsFormatter()

    snapshot_prev = {
        "capture_grab_time_ms": 100.0,
        "capture_grab_ops": 10,
        "fingerprint_time_ms": 50.0,
        "fingerprint_ops": 20,
    }

    snapshot_now = {
        "capture_grab_time_ms": 200.0,
        "capture_grab_ops": 20,
        "fingerprint_time_ms": 100.0,
        "fingerprint_ops": 40,
        "captured": 100,
        "decode_ok": 50,
        "assembled": 48,
        "duplicate_frames": 30,
        "dropped_queue_full": 0,
        "dropped_slot_unavailable": 0,
        "dropped_slot_starvation": 0,
        "decode_queue_depth": 0,
        "capture_overwrite_count": 0,
        "prep_backlog": 0,
        "assembled_bytes": 50000,
    }

    line = formatter.format_progress_line(
        snapshot_now,
        missing_count=10,
        delta_snapshot=snapshot_prev,
        delta_seconds=1.0,
    )

    # Check timing calculations: (time_delta / ops_delta)
    assert "grab_ms=10.00" in line  # (200-100)/(20-10)
    assert "fp_ms=2.50" in line  # (100-50)/(40-20)


def test_compact_formatter():
    """Test CompactStatsFormatter."""
    formatter = CompactStatsFormatter()
    snapshot = {
        "captured": 100,
        "decode_ok": 50,
        "decode_fail": 5,
        "assembled": 40,
        "decoded_new_chunks": 35,
        "decoded_duplicate_chunks": 7,
    }

    line = formatter.format_progress_line(snapshot, missing_count=10)

    assert (
        line
        == "captured=100 decode_ok=50 assembled=40 new_chunks=35 dup_chunks=7 "
        "decode_fail=5 missing_chunks=10"
    )


def test_compact_formatter_unknown_missing():
    """Test CompactStatsFormatter with unknown missing count."""
    formatter = CompactStatsFormatter()
    snapshot = {
        "captured": 100,
        "decode_ok": 50,
        "decode_fail": 5,
        "assembled": 40,
        "decoded_new_chunks": 35,
        "decoded_duplicate_chunks": 7,
    }

    line = formatter.format_progress_line(snapshot, missing_count=None)

    assert "missing_chunks=?" in line


def test_silent_reporter():
    """Test SilentProgressReporter produces no output."""
    reporter = SilentProgressReporter()

    # Should not raise any exceptions
    reporter.report_progress({"captured": 100}, missing_count=10, elapsed_seconds=5.0)
    reporter.report_completion(status="ok", output_path="/tmp/test", output_size_bytes=1000)
    reporter.report_error("test error")


def test_console_reporter_tracks_delta():
    """Test ConsoleProgressReporter tracks delta snapshots."""
    formatter = CompactStatsFormatter()
    reporter = ConsoleProgressReporter(formatter)

    # First call - no delta
    assert reporter.last_snapshot is None
    assert reporter.last_snapshot_time is None

    snapshot1 = {
        "captured": 100,
        "decode_ok": 50,
        "decode_fail": 0,
        "assembled": 40,
        "decoded_new_chunks": 35,
        "decoded_duplicate_chunks": 7,
    }
    reporter.report_progress(snapshot1, missing_count=10, elapsed_seconds=1.0)

    # Delta should be tracked
    assert reporter.last_snapshot is not None
    assert reporter.last_snapshot_time is not None
    assert reporter.last_snapshot["captured"] == 100

    # Second call - with delta
    snapshot2 = {
        "captured": 150,
        "decode_ok": 75,
        "decode_fail": 0,
        "assembled": 60,
        "decoded_new_chunks": 55,
        "decoded_duplicate_chunks": 10,
    }
    reporter.report_progress(snapshot2, missing_count=5, elapsed_seconds=2.0)

    # Delta should be updated
    assert reporter.last_snapshot["captured"] == 150


def test_console_reporter_completion_messages(capsys):
    """Test ConsoleProgressReporter completion messages."""
    formatter = CompactStatsFormatter()
    reporter = ConsoleProgressReporter(formatter)

    # Test success with path
    reporter.report_completion(status="ok", output_path="/tmp/test.tar.gz", output_size_bytes=1000)
    captured = capsys.readouterr()
    assert "restore complete: /tmp/test.tar.gz" in captured.out

    # Test success without path
    reporter.report_completion(status="ok", output_path="", output_size_bytes=1000)
    captured = capsys.readouterr()
    assert "Transfer complete: 1000 bytes" in captured.out

    # Test timeout
    reporter.report_completion(status="timeout_max_seconds", output_path="", output_size_bytes=0)
    captured = capsys.readouterr()
    assert "timeout: max-seconds reached" in captured.out


def test_console_reporter_error_message(capsys):
    """Test ConsoleProgressReporter error messages."""
    formatter = CompactStatsFormatter()
    reporter = ConsoleProgressReporter(formatter)

    reporter.report_error("test error message")
    captured = capsys.readouterr()
    assert "ERROR: test error message" in captured.out
