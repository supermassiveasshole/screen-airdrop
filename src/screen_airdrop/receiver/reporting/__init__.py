"""Reporting utilities for screen-airdrop receiver.

This module provides the new collector-based reporting system.

New architecture:
- Report: Pure data container
- Collector: Base interface for metric collectors
- EventCollector: Event-driven collector interface
- StatsCollector: Wraps Stats objects
- AssemblerCollector: Extracts assembler state
- ProtocolCollector: Protocol-specific debug info (Gray4, Layered)
- ReportCollector: Coordinates all collectors
"""

# New architecture exports
from screen_airdrop.receiver.reporting.assembler_collector import AssemblerCollector
from screen_airdrop.receiver.reporting.collector import Collector, EventCollector
from screen_airdrop.receiver.reporting.protocol_collector import (
    Gray4ProtocolCollector,
    LayeredProtocolCollector,
    ProtocolCollector,
    make_protocol_collector,
)
from screen_airdrop.receiver.reporting.report import Report
from screen_airdrop.receiver.reporting.report_collector import ReportCollector
from screen_airdrop.receiver.reporting.stats_collector import StatsCollector

__all__ = [
    "Report",
    "Collector",
    "EventCollector",
    "StatsCollector",
    "AssemblerCollector",
    "ProtocolCollector",
    "Gray4ProtocolCollector",
    "LayeredProtocolCollector",
    "ReportCollector",
    "make_protocol_collector",
]
