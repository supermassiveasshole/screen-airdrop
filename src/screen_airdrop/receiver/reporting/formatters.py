"""Statistics formatters for different pipeline types.

Each pipeline type (ScreenLive, Replay, etc.) has different metrics
and requires different formatting. This module provides formatters
that know how to extract and format pipeline-specific statistics.

Design principles:
- Single Responsibility: Each formatter handles one pipeline type
- Open/Closed: Easy to add new formatters for new pipeline types
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class StatsFormatter(ABC):
    """Abstract base class for statistics formatting."""

    @abstractmethod
    def format_progress_line(
        self,
        snapshot: Dict[str, Any],
        missing_count: Optional[int],
        delta_snapshot: Optional[Dict[str, Any]] = None,
        delta_seconds: float = 1.0,
    ) -> str:
        """Format a progress line from pipeline statistics.

        Args:
            snapshot: Current pipeline statistics snapshot
            missing_count: Number of missing chunks (None if unknown)
            delta_snapshot: Previous snapshot for rate calculations
            delta_seconds: Time elapsed since delta_snapshot

        Returns:
            Formatted progress line (without trailing newline)
        """
        pass


class ScreenLiveStatsFormatter(StatsFormatter):
    """Formatter for ScreenLiveRuntime statistics.

    Produces detailed output with:
    - Frame counts (captured, decoded, assembled, missing)
    - Drop statistics
    - FPS metrics (capture, prep, decode)
    - Queue depths
    - Throughput (KBps)
    - Timing breakdowns (grab, prep, decode, etc.)
    """

    def format_progress_line(
        self,
        snapshot: Dict[str, Any],
        missing_count: Optional[int],
        delta_snapshot: Optional[Dict[str, Any]] = None,
        delta_seconds: float = 1.0,
    ) -> str:
        """Format ScreenLiveRuntime progress line."""
        # Extract basic counters
        captured = int(snapshot.get("captured", 0))
        decoded = int(snapshot.get("decode_ok", 0))
        assembled = int(snapshot.get("assembled", 0))
        missing_str = "?" if missing_count is None else str(missing_count)
        dropped_queue = int(snapshot.get("dropped_queue_full", 0))
        dropped_slot = int(snapshot.get("dropped_slot_unavailable", 0))
        dropped_starvation = int(snapshot.get("dropped_slot_starvation", 0))
        dropped_total = dropped_queue + dropped_slot + dropped_starvation
        dropped_str = (
            f"{dropped_total}(q={dropped_queue} slot={dropped_slot} "
            f"starve={dropped_starvation})"
        )
        dedup = int(snapshot.get("duplicate_frames", 0))

        # Calculate FPS metrics
        if delta_snapshot is not None and delta_seconds > 0:
            cap_fps = self._calc_fps(
                snapshot.get("captured", 0),
                delta_snapshot.get("captured", 0),
                delta_seconds,
            )
            raw_grab_fps = self._calc_fps(
                snapshot.get("raw_grab_frames", 0),
                delta_snapshot.get("raw_grab_frames", 0),
                delta_seconds,
            )
            prep_fps = self._calc_fps(
                snapshot.get("prep_processed_frames", 0),
                delta_snapshot.get("prep_processed_frames", 0),
                delta_seconds,
            )
            accepted_fps = self._calc_fps(
                snapshot.get("accepted_for_decode_frames", 0),
                delta_snapshot.get("accepted_for_decode_frames", 0),
                delta_seconds,
            )
            dec_fps = self._calc_fps(
                snapshot.get("decode_ok", 0),
                delta_snapshot.get("decode_ok", 0),
                delta_seconds,
            )
        else:
            cap_fps = raw_grab_fps = prep_fps = accepted_fps = dec_fps = 0.0

        # Queue depths
        prep_backlog = int(snapshot.get("prep_backlog", 0))
        overwrite = int(snapshot.get("capture_overwrite_count", 0))
        decode_q = int(snapshot.get("decode_queue_depth", 0))

        # Throughput (based on new chunks only)
        if delta_snapshot is not None and delta_seconds > 0:
            rx_kBps = self._calc_throughput(
                snapshot.get("assembled_bytes", 0),
                delta_snapshot.get("assembled_bytes", 0),
                delta_seconds,
            )
            # Calculate new chunk rate (effective data rate)
            new_chunk_fps = self._calc_fps(
                snapshot.get("decoded_new_chunks", 0),
                delta_snapshot.get("decoded_new_chunks", 0),
                delta_seconds,
            )
        else:
            rx_kBps = 0.0
            new_chunk_fps = 0.0

        # Timing metrics (average per operation)
        grab_ms = self._calc_avg_timing(
            snapshot, delta_snapshot, "capture_grab_time_ms", "capture_grab_ops"
        )
        copy_ms = self._calc_avg_timing(
            snapshot, delta_snapshot, "capture_copy_time_ms", "capture_copy_ops"
        )
        ipc_recv_ms = self._calc_avg_timing(
            snapshot, delta_snapshot, "ipc_recv_time_ms", "ipc_recv_ops"
        )
        dedup_ms = self._calc_avg_timing(
            snapshot, delta_snapshot, "dedup_decision_ms", "dedup_decision_ops"
        )
        fp_ms = self._calc_avg_timing(
            snapshot, delta_snapshot, "fingerprint_time_ms", "fingerprint_ops"
        )
        mat_ms = self._calc_avg_timing(
            snapshot, delta_snapshot, "materialize_time_ms", "materialize_ops"
        )
        dump_ms = self._calc_avg_timing(
            snapshot, delta_snapshot, "dump_time_ms", "dump_ops"
        )

        # Format output line
        return (
            f"captured={captured} decoded={decoded} assembled={assembled} "
            f"missing={missing_str} dropped={dropped_str} dedup={dedup} "
            f"cap_fps={cap_fps:.2f} raw_grab_fps={raw_grab_fps:.2f} "
            f"prep_fps={prep_fps:.2f} accepted_fps={accepted_fps:.2f} "
            f"dec_fps={dec_fps:.2f} new_chunk_fps={new_chunk_fps:.2f} "
            f"prep_backlog={prep_backlog} overwrite={overwrite} decode_q={decode_q} "
            f"rx_KBps={rx_kBps:.2f} grab_ms={grab_ms:.2f} "
            f"copy_ms={copy_ms:.2f} ipc_recv_ms={ipc_recv_ms:.2f} "
            f"dedup_ms={dedup_ms:.2f} fp_ms={fp_ms:.2f} "
            f"mat_ms={mat_ms:.2f} dump_ms={dump_ms:.2f}"
        )

    def _calc_fps(
        self, current: Any, previous: Any, delta_seconds: float
    ) -> float:
        """Calculate FPS from counter delta."""
        delta = max(0, int(current or 0) - int(previous or 0))
        return delta / delta_seconds if delta_seconds > 0 else 0.0

    def _calc_throughput(
        self, current_bytes: Any, previous_bytes: Any, delta_seconds: float
    ) -> float:
        """Calculate throughput in KBps."""
        delta = max(0, int(current_bytes or 0) - int(previous_bytes or 0))
        return (delta / 1024.0) / delta_seconds if delta_seconds > 0 else 0.0

    def _calc_avg_timing(
        self,
        snapshot: Dict[str, Any],
        delta_snapshot: Optional[Dict[str, Any]],
        time_key: str,
        ops_key: str,
    ) -> float:
        """Calculate average timing per operation."""
        if delta_snapshot is None:
            return 0.0

        time_now = float(snapshot.get(time_key, 0.0))
        time_prev = float(delta_snapshot.get(time_key, 0.0))
        ops_now = int(snapshot.get(ops_key, 0))
        ops_prev = int(delta_snapshot.get(ops_key, 0))

        time_delta = max(0.0, time_now - time_prev)
        ops_delta = max(0, ops_now - ops_prev)

        return time_delta / ops_delta if ops_delta > 0 else 0.0


class CompactStatsFormatter(StatsFormatter):
    """Compact formatter for simple progress display.

    Produces minimal output suitable for:
    - CI/CD environments
    - Log files
    - Quick status checks
    """

    def format_progress_line(
        self,
        snapshot: Dict[str, Any],
        missing_count: Optional[int],
        delta_snapshot: Optional[Dict[str, Any]] = None,
        delta_seconds: float = 1.0,
    ) -> str:
        """Format compact progress line."""
        captured = int(snapshot.get("captured", 0))
        decode_ok = int(snapshot.get("decode_ok", 0))
        decode_fail = int(snapshot.get("decode_fail", 0))
        missing_str = "?" if missing_count is None else str(missing_count)

        return (
            f"captured={captured} decode_ok={decode_ok} "
            f"decode_fail={decode_fail} missing={missing_str}"
        )
