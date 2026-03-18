"""Factory for creating progress reporters."""

from screen_airdrop.receiver.runtime.console_reporter import ConsoleProgressReporter
from screen_airdrop.receiver.runtime.stats_formatter import (
    CompactStatsFormatter,
    ScreenLiveStatsFormatter,
)


def create_progress_reporter(source_type: str) -> ConsoleProgressReporter:
    """Create progress reporter with appropriate formatter.

    Args:
        source_type: Source type ("screen" or "replay")

    Returns:
        ConsoleProgressReporter instance with appropriate formatter
    """
    if source_type == "screen":
        # ScreenLiveRuntime uses detailed formatter
        formatter = ScreenLiveStatsFormatter()
    else:
        # Replay and other pipelines use compact formatter
        formatter = CompactStatsFormatter()

    return ConsoleProgressReporter(formatter)
