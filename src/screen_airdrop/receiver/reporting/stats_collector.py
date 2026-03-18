"""Statistics collector for wrapping Stats objects."""

from typing import Any, Dict

from screen_airdrop.receiver.reporting.collector import Collector


class StatsCollector(Collector):
    """Collects runtime statistics from Stats objects.

    This collector wraps existing TransferStats or ScreenLiveRuntimeStats
    objects and provides a unified interface for collecting statistics.

    StatsCollector is the single source of truth for all counters,
    including failure counts.
    """

    def __init__(self, stats):
        """Initialize stats collector.

        Args:
            stats: TransferStats or ScreenLiveRuntimeStats instance
        """
        self._stats = stats

    def collect(self) -> Dict[str, Any]:
        """Collect stats snapshot.

        For ScreenLiveRuntimeStats, this calls snapshot() which includes
        all runtime metrics and protocol-specific metrics.

        For TransferStats, this calls finalize() to get the final stats.

        Returns:
            Dictionary of statistics
        """
        # Check if stats has snapshot() method (ScreenLiveRuntimeStats)
        if hasattr(self._stats, 'snapshot'):
            return self._stats.snapshot()

        # Otherwise use finalize() (TransferStats)
        # Note: finalize() requires output_size_bytes and ts parameters
        # These will be provided by ReportCollector
        return {}

    def collect_finalized(self, output_size_bytes: int, ts: float) -> Dict[str, Any]:
        """Collect finalized stats.

        This method is used for TransferStats which requires output_size_bytes
        and ts parameters for finalization.

        For PipelineStats and ScreenLiveRuntimeStats (which don't have finalize()),
        this falls back to snapshot() and adds computed throughput metrics.

        Args:
            output_size_bytes: Size of output payload in bytes
            ts: Timestamp for finalization

        Returns:
            Dictionary of finalized statistics
        """
        # Check if stats has finalize() method (TransferStats)
        if hasattr(self._stats, 'finalize') and callable(getattr(self._stats, 'finalize')):
            return self._stats.finalize(output_size_bytes=output_size_bytes, ts=ts)

        # Otherwise use snapshot() (PipelineStats, ScreenLiveRuntimeStats)
        if hasattr(self._stats, 'snapshot'):
            snap = self._stats.snapshot()

            # Add computed metrics for stats without finalize()
            # Both PipelineStats and ScreenLiveRuntimeStats need these
            if hasattr(self._stats, 'start_ts'):
                total_elapsed = max(0.001, ts - self._stats.start_ts)

                # Compute goodput (assembled bytes / time)
                assembled_bytes = snap.get('assembled_bytes', 0)
                goodput_kibps = (float(assembled_bytes) / total_elapsed) / 1024.0

                # Compute end-to-end throughput (output size / time)
                end_to_end_kibps = (float(output_size_bytes) / total_elapsed) / 1024.0

                # Compute frame rates
                captured = snap.get('captured', 0)
                decode_ok = snap.get('decode_ok', 0)
                decode_fail = snap.get('decode_fail', 0)

                raw_frame_rate_fps = float(captured) / total_elapsed
                valid_frame_rate_fps = float(decode_ok) / total_elapsed
                bad_frame_rate = float(decode_fail) / float(captured) if captured > 0 else 0.0

                # Add throughput metrics
                snap['goodput_kibps'] = goodput_kibps
                snap['end_to_end_kibps'] = end_to_end_kibps
                snap['output_size_bytes'] = float(output_size_bytes)
                snap['raw_frame_rate_fps'] = raw_frame_rate_fps
                snap['valid_frame_rate_fps'] = valid_frame_rate_fps
                snap['bad_frame_rate'] = bad_frame_rate

                # Backward compatibility aliases
                snap['goodput_kbps'] = goodput_kibps
                snap['end_to_end_kbps'] = end_to_end_kibps

                # Add field name aliases for compatibility with TransferStats
                # PipelineStats uses different field names than TransferStats
                snap['bad_frames'] = decode_fail
                snap['valid_frames'] = decode_ok
                snap['total_frames'] = captured

                # Add timestamps
                snap['start_ts'] = self._stats.start_ts
                snap['done_ts'] = ts

            return snap

        return {}

    def reset(self) -> None:
        """Reset collector state.

        Stats objects are not reset during runtime, so this is a no-op.
        """
        pass
