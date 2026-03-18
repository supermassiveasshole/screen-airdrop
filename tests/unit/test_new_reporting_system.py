"""Unit tests for the new reporting system (Phase 1).

These tests verify the basic functionality of the new collector-based
reporting architecture.
"""

from types import SimpleNamespace

import pytest

from screen_airdrop.receiver.reporting import (
    AssemblerCollector,
    Gray4ProtocolCollector,
    LayeredProtocolCollector,
    Report,
    ReportCollector,
    StatsCollector,
    make_protocol_collector,
)


class TestReport:
    """Test the new pure Report class."""

    def test_report_basic_operations(self):
        """Test basic set/get/update operations."""
        report = Report()

        # Set single value
        report.set("key1", "value1")
        assert report.get("key1") == "value1"

        # Update multiple values
        report.update({"key2": "value2", "key3": 123})
        assert report.get("key2") == "value2"
        assert report.get("key3") == 123

        # Get with default
        assert report.get("nonexistent", "default") == "default"

    def test_report_finalization(self):
        """Test report finalization and immutability."""
        report = Report()
        report.set("key1", "value1")

        # Not finalized yet
        assert not report.is_finalized()

        # Finalize
        report.finalize_simple()
        assert report.is_finalized()

        # Cannot modify after finalization
        with pytest.raises(RuntimeError, match="Cannot modify finalized report"):
            report.set("key2", "value2")

        with pytest.raises(RuntimeError, match="Cannot modify finalized report"):
            report.update({"key3": "value3"})

    def test_report_to_dict(self):
        """Test to_dict returns a copy."""
        report = Report()
        report.update({"key1": "value1", "key2": 123})

        data = report.to_dict()
        assert data == {"key1": "value1", "key2": 123}

        # Modifying the returned dict should not affect the report
        data["key3"] = "value3"
        assert report.get("key3") is None


class TestGray4ProtocolCollector:
    """Test Gray4ProtocolCollector."""

    def test_on_decode_success(self):
        """Test recording decode success metadata."""
        collector = Gray4ProtocolCollector()

        meta = SimpleNamespace(
            mask_id=42,
            avg_symbol_confidence=0.95,
            total_decode_ms=12.5,
            payload_low_conf_symbols=3,
            payload_variant_attempts=2,
        )

        collector.on_decode_success(meta)

        data = collector.collect()
        assert data["gray4_last_mask_id"] == 42.0
        assert data["gray4_avg_symbol_confidence"] == 0.95
        assert data["gray4_total_decode_ms"] == 12.5
        assert data["gray4_payload_low_conf_symbols"] == 3
        assert data["gray4_payload_variant_attempts"] == 2

    def test_on_decode_failure(self):
        """Test recording decode failure details."""
        collector = Gray4ProtocolCollector()

        collector.on_decode_failure(
            error="payload CRC mismatch",
            failure_class="payload",
            context={"expected_crc": 0x1234, "got_crc": 0x5678}
        )

        data = collector.collect()
        assert data["gray4_last_failure_error"] == "payload CRC mismatch"
        assert data["gray4_last_failure_class"] == "payload"
        assert data["gray4_last_failure_context"] == {
            "expected_crc": 0x1234,
            "got_crc": 0x5678
        }

    def test_only_last_failure_recorded(self):
        """Test that only the last failure is recorded (not counted)."""
        collector = Gray4ProtocolCollector()

        # First failure
        collector.on_decode_failure("error 1", "header", {})

        # Second failure
        collector.on_decode_failure("error 2", "payload", {"detail": "info"})

        data = collector.collect()
        # Only the last failure is recorded
        assert data["gray4_last_failure_error"] == "error 2"
        assert data["gray4_last_failure_class"] == "payload"
        assert data["gray4_last_failure_context"] == {"detail": "info"}

        # No failure counts (handled by Stats)
        assert "gray4_failure_counts" not in data


class TestLayeredProtocolCollector:
    """Test LayeredProtocolCollector."""

    def test_on_decode_success(self):
        """Test recording decode success with control trace."""
        collector = LayeredProtocolCollector()

        meta = SimpleNamespace(
            control_trace={"bootstrap_attempt_count": 3, "threshold_value": 0.8}
        )

        collector.on_decode_success(meta)

        data = collector.collect()
        assert data["layered_last_control_trace"] == {
            "bootstrap_attempt_count": 3,
            "threshold_value": 0.8
        }

    def test_on_decode_failure(self):
        """Test recording decode failure details."""
        collector = LayeredProtocolCollector()

        collector.on_decode_failure(
            error="bootstrap RS decode failed",
            failure_class="header",
            context={"rs_layer": "bootstrap", "nsym": 10}
        )

        data = collector.collect()
        assert data["layered_last_failure_error"] == "bootstrap RS decode failed"
        assert data["layered_last_failure_class"] == "header"
        assert data["layered_last_failure_context"] == {
            "rs_layer": "bootstrap",
            "nsym": 10
        }


class TestMakeProtocolCollector:
    """Test make_protocol_collector factory function."""

    def test_gray4_collector(self):
        """Test creating gray4 collector."""
        collector = make_protocol_collector("gray4")
        assert isinstance(collector, Gray4ProtocolCollector)

    def test_layered_collector(self):
        """Test creating layered collector."""
        collector = make_protocol_collector("layered")
        assert isinstance(collector, LayeredProtocolCollector)

    def test_basic_no_collector(self):
        """Test basic protocol returns None."""
        collector = make_protocol_collector("basic")
        assert collector is None

    def test_compact_no_collector(self):
        """Test compact protocol returns None."""
        collector = make_protocol_collector("compact")
        assert collector is None

    def test_unknown_protocol(self):
        """Test unknown protocol returns None."""
        collector = make_protocol_collector("unknown")
        assert collector is None


class TestReportCollector:
    """Test ReportCollector coordination."""

    def test_basic_flow(self):
        """Test basic report collection flow."""
        # Mock stats collector
        class MockStatsCollector:
            def collect(self):
                return {"decode_ok": 10, "decode_fail": 2}

            def reset(self):
                pass

        # Mock assembler collector
        class MockAssemblerCollector:
            def collect(self):
                return {"missing_chunk_count": 0, "missing_chunk_ids": []}

            def reset(self):
                pass

        # Create report collector
        report_collector = ReportCollector(
            stats_collector=MockStatsCollector(),
            protocol_collector=None,  # No protocol collector for basic
            assembler_collector=MockAssemblerCollector(),
        )

        # Finalize report
        report = report_collector.finalize(
            status="ok",
            output_size_bytes=1024,
            output_path="/tmp/output.bin",
            ts=1000.0,
        )

        # Verify report contents
        assert report.is_finalized()
        data = report.to_dict()
        assert data["status"] == "ok"
        assert data["output_size_bytes"] == 1024
        assert data["output_path"] == "/tmp/output.bin"
        assert data["decode_ok"] == 10
        assert data["decode_fail"] == 2
        assert data["missing_chunk_count"] == 0

    def test_with_protocol_collector(self):
        """Test report collection with protocol collector."""
        # Mock stats collector
        class MockStatsCollector:
            def collect(self):
                return {"decode_ok": 5}

            def reset(self):
                pass

        # Mock assembler collector
        class MockAssemblerCollector:
            def collect(self):
                return {"missing_chunk_count": 0}

            def reset(self):
                pass

        # Create gray4 protocol collector
        protocol_collector = Gray4ProtocolCollector()
        protocol_collector.on_decode_failure("test error", "payload", {})

        # Create report collector
        report_collector = ReportCollector(
            stats_collector=MockStatsCollector(),
            protocol_collector=protocol_collector,
            assembler_collector=MockAssemblerCollector(),
        )

        # Finalize report
        report = report_collector.finalize(
            status="ok",
            output_size_bytes=512,
            output_path="",
            ts=2000.0,
        )

        # Verify protocol-specific fields are included
        data = report.to_dict()
        assert data["gray4_last_failure_error"] == "test error"
        assert data["gray4_last_failure_class"] == "payload"

    def test_event_forwarding(self):
        """Test that events are forwarded to protocol collector."""
        # Mock collectors
        class MockStatsCollector:
            def collect(self):
                return {}

            def reset(self):
                pass

        class MockAssemblerCollector:
            def collect(self):
                return {}

            def reset(self):
                pass

        # Create protocol collector
        protocol_collector = Gray4ProtocolCollector()

        # Create report collector
        report_collector = ReportCollector(
            stats_collector=MockStatsCollector(),
            protocol_collector=protocol_collector,
            assembler_collector=MockAssemblerCollector(),
        )

        # Send events
        meta = SimpleNamespace(mask_id=99, avg_symbol_confidence=0.99,
                              total_decode_ms=5.0, payload_low_conf_symbols=0,
                              payload_variant_attempts=1)
        report_collector.on_decode_success(meta)

        report_collector.on_decode_failure("test error", "header", {"detail": "info"})

        # Finalize and verify
        report = report_collector.finalize(
            status="ok", output_size_bytes=0, output_path="", ts=0.0
        )

        data = report.to_dict()
        assert data["gray4_last_mask_id"] == 99.0
        assert data["gray4_last_failure_error"] == "test error"
