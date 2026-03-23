"""Console progress reporter with pluggable formatters.

Implements console-based progress reporting with support for
different statistics formatters.
"""

import time
from typing import Any, Dict, Optional

from screen_airdrop.receiver.reporting.formatters import StatsFormatter
from screen_airdrop.receiver.reporting.reporter import ProgressReporter


class ConsoleProgressReporter(ProgressReporter):
    """Console-based progress reporter.

    Prints progress updates to stdout using a pluggable StatsFormatter.
    Tracks delta snapshots for rate calculations.
    """

    def __init__(self, formatter: StatsFormatter):
        """Initialize console reporter.

        Args:
            formatter: Statistics formatter to use
        """
        self.formatter = formatter
        self.last_snapshot: Optional[Dict[str, Any]] = None
        self.last_snapshot_time: Optional[float] = None

    def report_progress(
        self,
        snapshot: Dict[str, Any],
        missing_count: Optional[int],
        elapsed_seconds: float,
    ) -> None:
        """Report progress to console."""
        now = time.time()

        # Calculate delta for rate metrics
        delta_snapshot = self.last_snapshot
        delta_seconds = 1.0
        if self.last_snapshot_time is not None:
            delta_seconds = max(0.001, now - self.last_snapshot_time)

        # Format and print
        line = self.formatter.format_progress_line(
            snapshot=snapshot,
            missing_count=missing_count,
            delta_snapshot=delta_snapshot,
            delta_seconds=delta_seconds,
        )
        print(line)

        # Update tracking
        self.last_snapshot = snapshot.copy()
        self.last_snapshot_time = now

    def report_completion(
        self,
        status: str,
        output_path: str,
        output_size_bytes: int,
    ) -> None:
        """Report completion to console."""
        if status == "ok":
            if output_path:
                print(f"restore complete: {output_path}")
            else:
                print(f"Transfer complete: {output_size_bytes} bytes")
        elif status == "timeout_max_seconds":
            print("receiver timeout: max-seconds reached")
        elif status == "timeout_idle":
            print("receiver timeout: no valid frames")
        elif status == "aborted":
            print("receiver aborted by user")
        else:
            print(f"receiver completed with status: {status}")

    def report_error(self, error: str) -> None:
        """Report error to console."""
        print(f"ERROR: {error}")
