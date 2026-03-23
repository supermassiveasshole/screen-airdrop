"""Protocol-style interfaces for pluggable reporting components."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol

from screen_airdrop.receiver.reporting.report import Report


class ProgressReporterProtocol(Protocol):
    """Output backend for pipeline progress and completion events."""

    def report_progress(
        self,
        snapshot: Dict[str, Any],
        missing_count: Optional[int],
        elapsed_seconds: float,
    ) -> None: ...

    def report_completion(
        self,
        status: str,
        output_path: str,
        output_size_bytes: int,
    ) -> None: ...

    def report_error(self, error: str) -> None: ...


class ReportCollectorProtocol(Protocol):
    """Collector coordinator exposed to pipelines."""

    def on_decode_success(self, meta: Any) -> None: ...

    def on_decode_failure(
        self,
        error: str,
        failure_class: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None: ...
    def finalize(
        self,
        *,
        status: str,
        output_size_bytes: int,
        output_path: str,
        ts: float,
        pipeline_snap: Optional[Dict[str, Any]] = None,
    ) -> Report: ...


class CollectorProtocol(Protocol):
    """Minimal collector interface for report composition."""

    def collect(self) -> Dict[str, Any]: ...
    def reset(self) -> None: ...


class FinalizingStatsCollectorProtocol(CollectorProtocol, Protocol):
    """Stats collector that can finalize throughput-oriented fields."""

    def collect_finalized(self, output_size_bytes: int, ts: float) -> Dict[str, Any]: ...


class ProtocolCollectorProtocol(CollectorProtocol, Protocol):
    """Protocol-specific collector used by report composition."""

    protocol: str

    def set_pipeline_snapshot(self, snapshot: Dict[str, Any]) -> None: ...
    def on_decode_success(self, meta: Any) -> None: ...
    def on_decode_failure(
        self,
        error: str,
        failure_class: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None: ...
