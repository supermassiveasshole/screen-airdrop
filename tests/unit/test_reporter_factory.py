"""Tests for reporter_factory module."""

from screen_airdrop.receiver.reporting.console import ConsoleProgressReporter
from screen_airdrop.receiver.reporting.factory import create_progress_reporter
from screen_airdrop.receiver.reporting.formatters import (
    CompactStatsFormatter,
    ScreenLiveStatsFormatter,
)


def test_create_progress_reporter_screen():
    """Test creating progress reporter for screen source."""
    reporter = create_progress_reporter("screen")

    assert isinstance(reporter, ConsoleProgressReporter)
    assert isinstance(reporter.formatter, ScreenLiveStatsFormatter)


def test_create_progress_reporter_replay():
    """Test creating progress reporter for replay source."""
    reporter = create_progress_reporter("replay")

    assert isinstance(reporter, ConsoleProgressReporter)
    assert isinstance(reporter.formatter, CompactStatsFormatter)


def test_create_progress_reporter_other():
    """Test creating progress reporter for other source types uses compact formatter."""
    reporter = create_progress_reporter("other")

    assert isinstance(reporter, ConsoleProgressReporter)
    assert isinstance(reporter.formatter, CompactStatsFormatter)
