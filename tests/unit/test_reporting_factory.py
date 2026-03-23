"""Tests for registry-backed reporting factory helpers."""

import pytest

from screen_airdrop.receiver.reporting.console import ConsoleProgressReporter
from screen_airdrop.receiver.reporting.factory import (
    create_named_progress_reporter,
    create_stats_formatter,
    get_formatter_factory,
    get_progress_reporter_factory,
    registered_formatter_kinds,
    registered_progress_reporter_kinds,
)
from screen_airdrop.receiver.reporting.formatters import (
    CompactStatsFormatter,
    ScreenLiveStatsFormatter,
)
from screen_airdrop.receiver.reporting.reporter import SilentProgressReporter


def test_registered_formatter_kinds_include_defaults():
    assert registered_formatter_kinds() == ("compact", "screen")


def test_registered_progress_reporter_kinds_include_defaults():
    assert registered_progress_reporter_kinds() == ("console", "silent")


def test_create_screen_formatter():
    formatter = create_stats_formatter("screen")
    assert isinstance(formatter, ScreenLiveStatsFormatter)


def test_create_compact_formatter():
    formatter = create_stats_formatter("compact")
    assert isinstance(formatter, CompactStatsFormatter)


def test_create_named_console_progress_reporter():
    reporter = create_named_progress_reporter("console", formatter_kind="screen")
    assert isinstance(reporter, ConsoleProgressReporter)
    assert isinstance(reporter.formatter, ScreenLiveStatsFormatter)


def test_create_named_silent_progress_reporter():
    reporter = create_named_progress_reporter("silent", formatter_kind="compact")
    assert isinstance(reporter, SilentProgressReporter)


def test_unknown_formatter_kind_raises():
    with pytest.raises(ValueError, match="Unknown formatter kind: unknown"):
        get_formatter_factory("unknown")


def test_unknown_progress_reporter_kind_raises():
    with pytest.raises(ValueError, match="Unknown progress reporter kind: unknown"):
        get_progress_reporter_factory("unknown")
