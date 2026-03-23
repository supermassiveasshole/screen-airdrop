"""Stable reporting facade for receiver pipelines and application wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.receiver.reporting.factory import (
        create_named_progress_reporter,
        create_progress_reporter,
        create_report_collector,
        create_stats_formatter,
    )
    from screen_airdrop.receiver.reporting.interfaces import (
        ProgressReporterProtocol,
        ReportCollectorProtocol,
    )
    from screen_airdrop.receiver.reporting.report import Report

__all__ = [
    "Report",
    "ProgressReporterProtocol",
    "ReportCollectorProtocol",
    "create_named_progress_reporter",
    "create_progress_reporter",
    "create_report_collector",
    "create_stats_formatter",
]


def __getattr__(name):
    if name in {
        "create_named_progress_reporter",
        "create_progress_reporter",
        "create_report_collector",
        "create_stats_formatter",
    }:
        from screen_airdrop.receiver.reporting import factory as _factory

        return getattr(_factory, name)
    if name in {"ProgressReporterProtocol", "ReportCollectorProtocol"}:
        from screen_airdrop.receiver.reporting import interfaces as _interfaces

        return getattr(_interfaces, name)
    if name == "Report":
        from screen_airdrop.receiver.reporting.report import Report

        return Report
    raise AttributeError(name)
