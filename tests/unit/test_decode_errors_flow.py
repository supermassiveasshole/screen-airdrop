"""Test decode error flow: Decoder → Error → Worker → Coordinator → ProtocolCollector."""

import pytest

from screen_airdrop.receiver.decode_errors import (
    BasicHeaderDecodeError,
    BasicPayloadDecodeError,
    Gray4HeaderDecodeError,
    Gray4PayloadDecodeError,
    LayeredBodyDecodeError,
    LayeredBootstrapDecodeError,
)
from screen_airdrop.receiver.reporting.protocol_collector import (
    Gray4ProtocolCollector,
    LayeredProtocolCollector,
    make_protocol_collector,
)


class TestDecodeErrorAttributes:
    """Test that Error classes carry correct attributes."""

    def test_gray4_header_error_attributes(self):
        """Gray4 header error should have failure_class='header'."""
        error = Gray4HeaderDecodeError(
            "bad v3 magic", context={"expected": "SAR3", "got": "XXXX"}
        )
        assert error.message == "bad v3 magic"
        assert error.failure_class == "header"
        assert error.context == {"expected": "SAR3", "got": "XXXX"}

    def test_gray4_payload_error_attributes(self):
        """Gray4 payload error should have failure_class='payload'."""
        error = Gray4PayloadDecodeError(
            "payload CRC mismatch", context={"expected_crc": 0x1234, "got_crc": 0x5678}
        )
        assert error.message == "payload CRC mismatch"
        assert error.failure_class == "payload"
        assert error.context == {"expected_crc": 0x1234, "got_crc": 0x5678}

    def test_layered_bootstrap_error_attributes(self):
        """Layered bootstrap error should have failure_class='header'."""
        error = LayeredBootstrapDecodeError(
            "bootstrap RS decode failed",
            context={"rs_layer": "bootstrap", "correctable": False},
        )
        assert error.message == "bootstrap RS decode failed"
        assert error.failure_class == "header"
        assert error.context == {"rs_layer": "bootstrap", "correctable": False}

    def test_layered_body_error_attributes(self):
        """Layered body error should have failure_class='payload'."""
        error = LayeredBodyDecodeError(
            "body RS decode failed",
            context={"rs_layer": "body", "erasures": 10},
        )
        assert error.message == "body RS decode failed"
        assert error.failure_class == "payload"
        assert error.context == {"rs_layer": "body", "erasures": 10}

    def test_basic_header_error_attributes(self):
        """Basic header error should have failure_class='header'."""
        error = BasicHeaderDecodeError("format info decode failed")
        assert error.message == "format info decode failed"
        assert error.failure_class == "header"
        assert error.context == {}


class TestProtocolCollectorAttachFailure:
    """Test that ProtocolCollector correctly records error information."""

    def test_gray4_collector_attach_header_failure(self):
        """Gray4ProtocolCollector should record header failure details (no counts)."""
        collector = Gray4ProtocolCollector()

        # Simulate first header failure
        collector.on_decode_failure(
            error="bad v3 magic",
            failure_class="header",
            context={"expected": "SAR3", "got": "XXXX"},
        )

        data = collector.collect()
        assert data["gray4_last_failure_error"] == "bad v3 magic"
        assert data["gray4_last_failure_class"] == "header"
        assert data["gray4_last_failure_context"] == {
            "expected": "SAR3",
            "got": "XXXX",
        }

        # Simulate second header failure (overwrites previous)
        collector.on_decode_failure(
            error="format parity mismatch", failure_class="header", context={}
        )

        data = collector.collect()
        assert data["gray4_last_failure_error"] == "format parity mismatch"
        assert data["gray4_last_failure_class"] == "header"

    def test_gray4_collector_attach_payload_failure(self):
        """Gray4ProtocolCollector should record payload failure details (no counts)."""
        collector = Gray4ProtocolCollector()

        collector.on_decode_failure(
            error="payload CRC mismatch",
            failure_class="payload",
            context={"expected_crc": 0x1234, "got_crc": 0x5678},
        )

        data = collector.collect()
        assert data["gray4_last_failure_error"] == "payload CRC mismatch"
        assert data["gray4_last_failure_class"] == "payload"
        assert data["gray4_last_failure_context"] == {
            "expected_crc": 0x1234,
            "got_crc": 0x5678,
        }

    def test_layered_collector_attach_bootstrap_failure(self):
        """LayeredProtocolCollector should record bootstrap failure details (no counts)."""
        collector = LayeredProtocolCollector()

        collector.on_decode_failure(
            error="bootstrap RS decode failed",
            failure_class="header",
            context={"rs_layer": "bootstrap", "correctable": False},
        )

        data = collector.collect()
        assert data["layered_last_failure_error"] == "bootstrap RS decode failed"
        assert data["layered_last_failure_class"] == "header"
        assert data["layered_last_failure_context"] == {
            "rs_layer": "bootstrap",
            "correctable": False,
        }

    def test_layered_collector_attach_body_failure(self):
        """LayeredProtocolCollector should record body failure details (no counts)."""
        collector = LayeredProtocolCollector()

        collector.on_decode_failure(
            error="body RS decode failed",
            failure_class="payload",
            context={"rs_layer": "body", "erasures": 10},
        )

        data = collector.collect()
        assert data["layered_last_failure_error"] == "body RS decode failed"
        assert data["layered_last_failure_class"] == "payload"
        assert data["layered_last_failure_context"] == {
            "rs_layer": "body",
            "erasures": 10,
        }

    def test_basic_protocol_no_collector(self):
        """Basic protocol should not have a ProtocolCollector."""
        collector = make_protocol_collector("basic")
        assert collector is None


class TestProtocolCollectorRecordsLastFailureOnly:
    """Test that ProtocolCollector only records the last failure, not counts."""

    def test_gray4_collector_overwrites_previous_failure(self):
        """Gray4ProtocolCollector should overwrite previous failure with new one."""
        collector = Gray4ProtocolCollector()

        # First failure: header
        collector.on_decode_failure("bad magic", "header", {})
        data = collector.collect()
        assert data["gray4_last_failure_error"] == "bad magic"
        assert data["gray4_last_failure_class"] == "header"

        # Second failure: payload (overwrites header)
        collector.on_decode_failure(
            "CRC mismatch", "payload", {"expected_crc": 0x1234, "got_crc": 0x5678}
        )
        data = collector.collect()
        assert data["gray4_last_failure_error"] == "CRC mismatch"
        assert data["gray4_last_failure_class"] == "payload"
        assert data["gray4_last_failure_context"] == {
            "expected_crc": 0x1234,
            "got_crc": 0x5678,
        }

        # Third failure: payload again (overwrites previous payload)
        collector.on_decode_failure("CRC mismatch", "payload", {})
        data = collector.collect()
        assert data["gray4_last_failure_error"] == "CRC mismatch"
        assert data["gray4_last_failure_class"] == "payload"
        # Context should not be included when empty
        assert "gray4_last_failure_context" not in data

    def test_layered_collector_overwrites_previous_failure(self):
        """LayeredProtocolCollector should overwrite previous failure with new one."""
        collector = LayeredProtocolCollector()

        # First failure: bootstrap
        collector.on_decode_failure("bootstrap RS failed", "header", {})
        data = collector.collect()
        assert data["layered_last_failure_error"] == "bootstrap RS failed"
        assert data["layered_last_failure_class"] == "header"

        # Second failure: body (overwrites bootstrap)
        collector.on_decode_failure(
            "body RS failed", "payload", {"rs_layer": "body", "erasures": 10}
        )
        data = collector.collect()
        assert data["layered_last_failure_error"] == "body RS failed"
        assert data["layered_last_failure_class"] == "payload"
        assert data["layered_last_failure_context"] == {
            "rs_layer": "body",
            "erasures": 10,
        }


class TestErrorInheritance:
    """Test that Error classes have correct inheritance."""

    def test_gray4_errors_inherit_from_gray4_decode_error(self):
        """Gray4 errors should inherit from Gray4DecodeError."""
        from screen_airdrop.receiver.decode_errors import Gray4DecodeError

        header_err = Gray4HeaderDecodeError("test")
        payload_err = Gray4PayloadDecodeError("test")

        assert isinstance(header_err, Gray4DecodeError)
        assert isinstance(payload_err, Gray4DecodeError)

    def test_layered_errors_inherit_from_layered_decode_error(self):
        """Layered errors should inherit from LayeredDecodeError."""
        from screen_airdrop.receiver.decode_errors import LayeredDecodeError

        bootstrap_err = LayeredBootstrapDecodeError("test")
        body_err = LayeredBodyDecodeError("test")

        assert isinstance(bootstrap_err, LayeredDecodeError)
        assert isinstance(body_err, LayeredDecodeError)

    def test_all_errors_inherit_from_decode_error(self):
        """All protocol errors should inherit from DecodeError."""
        from screen_airdrop.receiver.decode_errors import DecodeError

        errors = [
            Gray4HeaderDecodeError("test"),
            Gray4PayloadDecodeError("test"),
            LayeredBootstrapDecodeError("test"),
            LayeredBodyDecodeError("test"),
            BasicHeaderDecodeError("test"),
            BasicPayloadDecodeError("test"),
        ]

        for err in errors:
            assert isinstance(err, DecodeError)
            assert isinstance(err, Exception)
