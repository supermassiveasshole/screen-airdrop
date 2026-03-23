"""Protocol-style interfaces for pluggable receiver pipelines."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol

from screen_airdrop.receiver.reporting.interfaces import ReportCollectorProtocol


class PipelineProtocol(Protocol):
    """Minimal interface shared by decode pipeline implementations."""

    protocol: str
    done_event: Any

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def wait(self, timeout: Optional[float] = None) -> bool: ...
    def join(self, timeout: float = 10.0) -> None: ...
    def check_errors(self) -> None: ...
    def snapshot(self) -> Dict[str, Any]: ...
    def get_report_collector(self) -> Optional[ReportCollectorProtocol]: ...


class PipelineFactoryProtocol(Protocol):
    """Factory interface for constructing pipeline implementations."""

    def __call__(self, *args: Any, **kwargs: Any) -> PipelineProtocol: ...

