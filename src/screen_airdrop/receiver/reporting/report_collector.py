"""Report collector coordinator.

This module provides the ReportCollector class which coordinates multiple
collectors to build a complete report. It replaces the old Report + ReportBuilder
architecture with a cleaner, more modular design.
"""

from typing import Any, Dict, List, Optional, cast

from screen_airdrop.receiver.reporting.interfaces import (
    CollectorProtocol,
    FinalizingStatsCollectorProtocol,
    ProtocolCollectorProtocol,
)
from screen_airdrop.receiver.reporting.report import Report


class ReportCollector:
    """Coordinates multiple collectors to build a complete report.

    This is the main entry point for the new reporting system.
    It replaces the old Report + ReportBuilder architecture.

    ReportCollector:
    - Holds a Report object (pure data container)
    - Coordinates StatsCollector, ProtocolCollector, AssemblerCollector
    - Provides on_decode_success/failure event handlers
    - Provides finalize() to generate the final report
    """

    def __init__(
        self,
        *,
        stats_collector: CollectorProtocol,
        protocol_collector: Optional[ProtocolCollectorProtocol] = None,
        assembler_collector: CollectorProtocol,
        additional_collectors: Optional[List[CollectorProtocol]] = None,
    ):
        """Initialize report collector.

        Args:
            stats_collector: Statistics collector
            protocol_collector: Protocol-specific event collector (optional)
            assembler_collector: Assembler state collector
            additional_collectors: Additional collectors (optional)
        """
        self._report = Report()
        self._stats_collector = stats_collector
        self._protocol_collector = protocol_collector
        self._assembler_collector = assembler_collector
        self._additional_collectors = additional_collectors or []

    def get_report(self) -> Report:
        """Get the report object.

        Returns:
            Report instance (may not be finalized yet)
        """
        return self._report

    def on_decode_success(self, meta: Any) -> None:
        """Handle decode success event."""
        if self._protocol_collector is not None:
            self._protocol_collector.on_decode_success(meta)

    def on_decode_failure(
        self,
        error: str,
        failure_class: str,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Handle decode failure event."""
        if self._protocol_collector is not None:
            self._protocol_collector.on_decode_failure(error, failure_class, context)

    def finalize(
        self,
        *,
        status: str,
        output_size_bytes: int,
        output_path: str,
        ts: float,
        pipeline_snap: Optional[Dict[str, Any]] = None,
    ) -> Report:
        """Finalize report by collecting from all collectors.

        This method:
        1. Sets basic transfer information
        2. Collects from StatsCollector
        3. Collects from ProtocolCollector (if present)
        4. Collects from AssemblerCollector
        5. Collects from additional collectors
        6. Adds pipeline snapshot (if provided)
        7. Finalizes the report (makes it immutable)

        Args:
            status: Transfer status (ok, timeout_max_seconds, timeout_idle, aborted)
            output_size_bytes: Size of output payload in bytes
            output_path: Path to output file (if successful)
            ts: Timestamp for finalization
            pipeline_snap: Optional pipeline-specific snapshot

        Returns:
            Finalized Report object
        """
        # Set basic info
        self._report.update({
            "status": status,
            "output_size_bytes": output_size_bytes,
            "output_path": output_path if output_path else "",
        })

        # Collect from stats collector
        # Use collect_finalized for TransferStats which needs parameters
        if hasattr(self._stats_collector, "collect_finalized"):
            finalized_collector = cast(FinalizingStatsCollectorProtocol, self._stats_collector)
            stats_data = finalized_collector.collect_finalized(
                output_size_bytes=output_size_bytes,
                ts=ts,
            )
        else:
            stats_data = self._stats_collector.collect()

        self._report.update(stats_data)

        # Collect from protocol collector
        if self._protocol_collector:
            # Set pipeline snapshot for protocol collector to extract data
            if pipeline_snap:
                self._protocol_collector.set_pipeline_snapshot(pipeline_snap)

            protocol_data = self._protocol_collector.collect()
            if protocol_data:
                # Add protocol_debug if protocol collector provides structured debug info
                # (e.g., layered_debug, gray4_debug)
                protocol_name = getattr(self._protocol_collector, 'protocol', 'unknown')
                debug_key = f"{protocol_name}_debug"
                if debug_key in protocol_data:
                    # Protocol collector provides structured debug info
                    self._report.update({
                        "protocol_debug": protocol_data
                    })
                else:
                    # Protocol collector only provides flat fields
                    self._report.update(protocol_data)

        # Collect from assembler collector
        assembler_data = self._assembler_collector.collect()
        self._report.update(assembler_data)

        # Collect from additional collectors
        for collector in self._additional_collectors:
            collector_data = collector.collect()
            self._report.update(collector_data)

        # Add pipeline snapshot if provided
        if pipeline_snap:
            self._report.update(pipeline_snap)

        # Finalize (make immutable)
        self._report.finalize_simple()

        return self._report
