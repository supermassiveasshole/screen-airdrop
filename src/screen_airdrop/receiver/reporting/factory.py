"""Registry-backed factory helpers for pluggable reporting components."""

from __future__ import annotations

from typing import Callable, Optional

from screen_airdrop.receiver.reporting.assembler_collector import AssemblerCollector
from screen_airdrop.receiver.reporting.console import ConsoleProgressReporter
from screen_airdrop.receiver.reporting.formatters import (
    CompactStatsFormatter,
    ScreenLiveStatsFormatter,
    StatsFormatter,
)
from screen_airdrop.receiver.reporting.interfaces import CollectorProtocol, ProgressReporterProtocol
from screen_airdrop.receiver.reporting.protocol_collector import make_protocol_collector
from screen_airdrop.receiver.reporting.report_collector import ReportCollector
from screen_airdrop.receiver.reporting.reporter import SilentProgressReporter
from screen_airdrop.receiver.reporting.stats_collector import StatsCollector

FormatterFactory = Callable[[], StatsFormatter]
ProgressReporterFactory = Callable[..., ProgressReporterProtocol]


def _create_console_reporter(*, formatter: StatsFormatter) -> ConsoleProgressReporter:
    return ConsoleProgressReporter(formatter)


def _create_silent_reporter(*, formatter: StatsFormatter) -> SilentProgressReporter:
    del formatter
    return SilentProgressReporter()


_FORMATTER_FACTORIES: dict[str, FormatterFactory] = {
    "compact": CompactStatsFormatter,
    "screen": ScreenLiveStatsFormatter,
}

_PROGRESS_REPORTER_FACTORIES: dict[str, ProgressReporterFactory] = {
    "console": _create_console_reporter,
    "silent": _create_silent_reporter,
}

_SOURCE_DEFAULT_FORMATTERS: dict[str, str] = {
    "screen": "screen",
    "replay": "compact",
    "simulated_live": "compact",
}

_SOURCE_DEFAULT_REPORTERS: dict[str, str] = {
    "screen": "console",
    "replay": "console",
    "simulated_live": "console",
}


def register_formatter_factory(name: str, factory: FormatterFactory) -> None:
    """Register or replace a named stats formatter factory."""
    _FORMATTER_FACTORIES[str(name)] = factory


def get_formatter_factory(name: str) -> FormatterFactory:
    """Return the registered formatter factory for a formatter kind."""
    try:
        return _FORMATTER_FACTORIES[str(name)]
    except KeyError as exc:
        raise ValueError(f"Unknown formatter kind: {name}") from exc


def create_stats_formatter(name: str) -> StatsFormatter:
    """Instantiate a registered stats formatter."""
    factory = get_formatter_factory(name)
    return factory()


def registered_formatter_kinds():
    """Return registered formatter kinds in deterministic order."""
    return tuple(sorted(_FORMATTER_FACTORIES))


def register_progress_reporter_factory(name: str, factory: ProgressReporterFactory) -> None:
    """Register or replace a named progress reporter factory."""
    _PROGRESS_REPORTER_FACTORIES[str(name)] = factory


def get_progress_reporter_factory(name: str) -> ProgressReporterFactory:
    """Return the registered progress reporter factory for a reporter kind."""
    try:
        return _PROGRESS_REPORTER_FACTORIES[str(name)]
    except KeyError as exc:
        raise ValueError(f"Unknown progress reporter kind: {name}") from exc


def create_named_progress_reporter(
    reporter_kind: str,
    *,
    formatter_kind: str,
) -> ProgressReporterProtocol:
    """Instantiate a named reporter with a named formatter."""
    reporter_factory = get_progress_reporter_factory(reporter_kind)
    formatter = create_stats_formatter(formatter_kind)
    return reporter_factory(formatter=formatter)


def registered_progress_reporter_kinds():
    """Return registered reporter kinds in deterministic order."""
    return tuple(sorted(_PROGRESS_REPORTER_FACTORIES))


def create_progress_reporter(source_type: str) -> ProgressReporterProtocol:
    """Create the default progress reporter for a source type."""
    source_key = str(source_type)
    formatter_kind = _SOURCE_DEFAULT_FORMATTERS.get(source_key, "compact")
    reporter_kind = _SOURCE_DEFAULT_REPORTERS.get(source_key, "console")
    return create_named_progress_reporter(
        reporter_kind,
        formatter_kind=formatter_kind,
    )


def create_report_collector(
    *,
    protocol: str,
    stats,
    assembler,
    additional_collectors: Optional[list[CollectorProtocol]] = None,
) -> ReportCollector:
    """Create the repository-standard report collector composition."""
    return ReportCollector(
        stats_collector=StatsCollector(stats),
        protocol_collector=make_protocol_collector(protocol),
        assembler_collector=AssemblerCollector(assembler),
        additional_collectors=additional_collectors,
    )
