"""Progress reporting abstraction for pipeline monitoring.

This module provides a pluggable progress reporting system that supports:
- Console output (current implementation)
- GUI progress bars (future)
- Silent mode (testing)

Design principles:
- Single Responsibility: Each reporter handles one output method
- Open/Closed: Easy to add new reporters without modifying existing code
- Dependency Inversion: Pipeline depends on abstraction, not concrete reporters
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class ProgressReporter(ABC):
    """Abstract base class for progress reporting.

    Different pipeline types can use different reporters, and the same
    pipeline can switch reporters (e.g., CLI vs GUI mode).
    """

    @abstractmethod
    def report_progress(
        self,
        snapshot: Dict[str, Any],
        missing_count: Optional[int],
        elapsed_seconds: float,
    ) -> None:
        """Report current progress.

        Args:
            snapshot: Pipeline statistics snapshot
            missing_count: Number of missing chunks (None if unknown)
            elapsed_seconds: Time elapsed since start
        """
        pass

    @abstractmethod
    def report_completion(
        self,
        status: str,
        output_path: str,
        output_size_bytes: int,
    ) -> None:
        """Report completion status.

        Args:
            status: Completion status ("ok", "timeout", "aborted", etc.)
            output_path: Path to output file (empty if none)
            output_size_bytes: Size of output in bytes
        """
        pass

    @abstractmethod
    def report_error(self, error: str) -> None:
        """Report an error.

        Args:
            error: Error message
        """
        pass


class SilentProgressReporter(ProgressReporter):
    """Silent reporter that produces no output.

    Useful for:
    - Automated testing
    - Batch processing
    - When output is handled elsewhere
    """

    def report_progress(
        self,
        snapshot: Dict[str, Any],
        missing_count: Optional[int],
        elapsed_seconds: float,
    ) -> None:
        pass

    def report_completion(
        self,
        status: str,
        output_path: str,
        output_size_bytes: int,
    ) -> None:
        pass

    def report_error(self, error: str) -> None:
        pass
