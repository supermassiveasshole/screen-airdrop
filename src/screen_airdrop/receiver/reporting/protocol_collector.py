"""Protocol-specific debug collectors.

This module provides collectors for protocol-specific debug information.
Protocol collectors extract data from the final pipeline snapshot rather
than collecting events in real-time, to avoid performance overhead.
"""

from typing import Any, Dict, Optional

from screen_airdrop.receiver.reporting.collector import Collector


class ProtocolCollector(Collector):
    """Base class for protocol-specific collectors.

    Protocol collectors extract protocol-specific debug information
    from the final pipeline snapshot. They do NOT listen to events
    during runtime to avoid performance overhead.
    """

    def __init__(self, protocol: str):
        """Initialize protocol collector.

        Args:
            protocol: Protocol name (gray4, layered, etc.)
        """
        self.protocol = protocol
        self._pipeline_snap: Optional[Dict[str, Any]] = None

    def set_pipeline_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """Set pipeline snapshot for extraction.

        Args:
            snapshot: Pipeline statistics snapshot
        """
        self._pipeline_snap = snapshot

    def collect(self) -> Dict[str, Any]:
        """Collect protocol-specific metrics from pipeline snapshot.

        Returns:
            Dictionary of protocol-specific fields
        """
        return {}

    def reset(self) -> None:
        """Reset protocol state."""
        self._pipeline_snap = None


class Gray4ProtocolCollector(ProtocolCollector):
    """Gray4 protocol debug collector.

    Extracts gray4-specific metrics from pipeline snapshot and
    constructs the gray4_debug structure expected by tests.
    """

    def __init__(self):
        """Initialize gray4 collector."""
        super().__init__("gray4")

    def collect(self) -> Dict[str, Any]:
        """Extract gray4 metrics from pipeline snapshot.

        Returns:
            Dictionary with gray4_debug structure
        """
        if not self._pipeline_snap:
            return {}

        # Extract gray4-specific fields from snapshot
        result = {}

        # Extract all gray4_* fields
        for key, value in self._pipeline_snap.items():
            if key.startswith("gray4_"):
                result[key] = value

        # Construct gray4_debug structure if we have gray4 fields
        if result:
            # Build gray4_debug structure
            gray4_debug: Dict[str, Any] = {}

            # Extract failure_counts
            failure_counts = {}
            for failure_type in ["header", "payload", "locator", "unknown"]:
                key = f"gray4_failure_count_{failure_type}"
                if key in result:
                    failure_counts[failure_type] = result[key]
            if failure_counts:
                gray4_debug["failure_counts"] = failure_counts

            # Add gray4_debug to result
            if gray4_debug:
                result["gray4_debug"] = gray4_debug

        return result


class LayeredProtocolCollector(ProtocolCollector):
    """Layered protocol debug collector.

    Extracts layered-specific metrics from pipeline snapshot and
    constructs the layered_debug structure expected by tests.
    """

    def __init__(self):
        """Initialize layered collector."""
        super().__init__("layered")

    def collect(self) -> Dict[str, Any]:
        """Extract layered metrics from pipeline snapshot.

        Returns:
            Dictionary with layered_debug structure
        """
        if not self._pipeline_snap:
            return {}

        # Extract layered-specific fields from snapshot
        result = {}

        # Extract all layered_* fields
        for key, value in self._pipeline_snap.items():
            if key.startswith("layered_"):
                result[key] = value

        # Construct layered_debug structure if we have layered fields
        if result:
            # Build layered_debug structure from available fields
            layered_debug: Dict[str, Any] = {}

            # Extract control_path_version
            if "layered_control_path_version" in result:
                layered_debug["control_path_version"] = result["layered_control_path_version"]

            # Extract core_header stats
            core_header = {}
            for key in ["raw_bytes", "coded_bytes", "ecc_nsym", "attempt_count",
                       "threshold_avg", "vote_margin_min", "vote_margin_avg",
                       "erasure_symbol_count_avg", "erasure_symbol_count_max",
                       "errata_corrected_avg", "errata_corrected_max",
                       "rs_fail_count", "crc_fail_count"]:
                full_key = f"layered_bootstrap_{key}"
                if full_key in result:
                    core_header[key] = result[full_key]
            if "layered_bootstrap_fail_examples" in result:
                core_header["fail_examples"] = result["layered_bootstrap_fail_examples"]
            if core_header:
                layered_debug["core_header"] = core_header

            # Extract body stats
            body = {}
            if "layered_body_rs_fail_count" in result:
                body["rs_fail_count"] = result["layered_body_rs_fail_count"]
            if "layered_body_crc_fail_count" in result:
                body["crc_fail_count"] = result["layered_body_crc_fail_count"]
            if body:
                layered_debug["body"] = body

            # Extract decode_stage_counts
            if "layered_decode_stage_counts" in result:
                layered_debug["decode_stage_counts"] = result["layered_decode_stage_counts"]

            # Add layered_debug to result
            if layered_debug:
                result["layered_debug"] = layered_debug

        return result


def make_protocol_collector(protocol: str) -> Optional[ProtocolCollector]:
    """Create protocol-specific collector.

    Factory function for creating the appropriate collector based on protocol.

    Args:
        protocol: Protocol name (basic, compact, gray4, layered)

    Returns:
        Protocol collector or None for protocols without debug info
    """
    if protocol == "gray4":
        return Gray4ProtocolCollector()
    elif protocol == "layered":
        return LayeredProtocolCollector()
    elif protocol in ("basic", "compact"):
        # Basic and compact protocols don't have protocol-specific debug info
        return None
    else:
        # Unknown protocol - no collector
        return None
