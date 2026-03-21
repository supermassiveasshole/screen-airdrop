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

    def on_decode_success(self, meta: Any) -> None:
        """Record protocol-specific success metadata."""

    def on_decode_failure(
        self,
        error: str,
        failure_class: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record protocol-specific failure metadata."""

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
        self._last_failure_error = ""
        self._last_failure_class = ""
        self._last_failure_context: Dict[str, Any] = {}
        self._last_mask_id = -1.0
        self._avg_symbol_confidence = 0.0
        self._total_decode_ms = 0.0
        self._payload_low_conf_symbols = 0
        self._payload_variant_attempts = 0

    def collect(self) -> Dict[str, Any]:
        """Extract gray4 metrics from pipeline snapshot.

        Returns:
            Dictionary with gray4_debug structure
        """
        if self._pipeline_snap:
            result: Dict[str, Any] = {}
            for key, value in self._pipeline_snap.items():
                if key.startswith("gray4_"):
                    result[key] = value
            if result:
                gray4_debug: Dict[str, Any] = {}
                failure_counts = {}
                for failure_type in ["header", "payload", "locator", "unknown"]:
                    key = f"gray4_failure_count_{failure_type}"
                    if key in result:
                        failure_counts[failure_type] = result[key]
                if failure_counts:
                    gray4_debug["failure_counts"] = failure_counts
                if gray4_debug:
                    result["gray4_debug"] = gray4_debug
                return result

        result = {
            "gray4_last_failure_error": self._last_failure_error,
            "gray4_last_failure_class": self._last_failure_class,
            "gray4_last_mask_id": self._last_mask_id,
            "gray4_avg_symbol_confidence": self._avg_symbol_confidence,
            "gray4_total_decode_ms": self._total_decode_ms,
            "gray4_payload_low_conf_symbols": self._payload_low_conf_symbols,
            "gray4_payload_variant_attempts": self._payload_variant_attempts,
        }
        if self._last_failure_context:
            result["gray4_last_failure_context"] = dict(self._last_failure_context)
        return result

    def on_decode_success(self, meta: Any) -> None:
        self._last_mask_id = float(getattr(meta, "mask_id", -1))
        self._avg_symbol_confidence = float(getattr(meta, "avg_symbol_confidence", 0.0))
        self._total_decode_ms = float(getattr(meta, "total_decode_ms", 0.0))
        self._payload_low_conf_symbols = int(getattr(meta, "payload_low_conf_symbols", 0))
        self._payload_variant_attempts = int(getattr(meta, "payload_variant_attempts", 0))

    def on_decode_failure(
        self,
        error: str,
        failure_class: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._last_failure_error = str(error)
        self._last_failure_class = str(failure_class)
        self._last_failure_context = {} if context is None else dict(context)


class LayeredProtocolCollector(ProtocolCollector):
    """Layered protocol debug collector.

    Extracts layered-specific metrics from pipeline snapshot and
    constructs the layered_debug structure expected by tests.
    """

    def __init__(self):
        """Initialize layered collector."""
        super().__init__("layered")
        self._last_control_trace: Dict[str, Any] = {}
        self._last_failure_error = ""
        self._last_failure_class = ""
        self._last_failure_context: Dict[str, Any] = {}

    def collect(self) -> Dict[str, Any]:
        """Extract layered metrics from pipeline snapshot.

        Returns:
            Dictionary with layered_debug structure
        """
        if self._pipeline_snap:
            result: Dict[str, Any] = {}
            for key, value in self._pipeline_snap.items():
                if key.startswith("layered_"):
                    result[key] = value
            if result:
                layered_debug: Dict[str, Any] = {}
                if "layered_control_path_version" in result:
                    layered_debug["control_path_version"] = result["layered_control_path_version"]

                core_header = {}
                for key in [
                    "raw_bytes",
                    "coded_bytes",
                    "ecc_nsym",
                    "attempt_count",
                    "threshold_avg",
                    "vote_margin_min",
                    "vote_margin_avg",
                    "erasure_symbol_count_avg",
                    "erasure_symbol_count_max",
                    "errata_corrected_avg",
                    "errata_corrected_max",
                    "rs_fail_count",
                    "crc_fail_count",
                ]:
                    full_key = f"layered_bootstrap_{key}"
                    if full_key in result:
                        core_header[key] = result[full_key]
                if "layered_bootstrap_fail_examples" in result:
                    core_header["fail_examples"] = result["layered_bootstrap_fail_examples"]
                if core_header:
                    layered_debug["core_header"] = core_header

                body = {}
                if "layered_body_rs_fail_count" in result:
                    body["rs_fail_count"] = result["layered_body_rs_fail_count"]
                if "layered_body_crc_fail_count" in result:
                    body["crc_fail_count"] = result["layered_body_crc_fail_count"]
                if body:
                    layered_debug["body"] = body

                if "layered_decode_stage_counts" in result:
                    layered_debug["decode_stage_counts"] = result["layered_decode_stage_counts"]

                if layered_debug:
                    result["layered_debug"] = layered_debug
                return result

        result = {
            "layered_last_control_trace": dict(self._last_control_trace),
            "layered_last_failure_error": self._last_failure_error,
            "layered_last_failure_class": self._last_failure_class,
        }
        if self._last_failure_context:
            result["layered_last_failure_context"] = dict(self._last_failure_context)
        return result

    def on_decode_success(self, meta: Any) -> None:
        control_trace = getattr(meta, "control_trace", None)
        self._last_control_trace = (
            {} if not isinstance(control_trace, dict) else dict(control_trace)
        )

    def on_decode_failure(
        self,
        error: str,
        failure_class: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._last_failure_error = str(error)
        self._last_failure_class = str(failure_class)
        self._last_failure_context = {} if context is None else dict(context)


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
