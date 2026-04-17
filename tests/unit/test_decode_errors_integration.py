"""Integration test: Worker extracts Error attributes → Coordinator records to ReportCollector."""

from dataclasses import dataclass

from screen_airdrop.receiver.decode_errors import (
    DecodeError,
    Gray4HeaderDecodeError,
    Gray4PayloadDecodeError,
    LayeredBodyDecodeError,
    LayeredBootstrapDecodeError,
)
from screen_airdrop.receiver.reporting.protocol_collector import (
    Gray4ProtocolCollector,
    LayeredProtocolCollector,
)
from screen_airdrop.receiver.runtime.events import DecodeCompletion, FrameSlotDescriptor


@dataclass
class MockStats:
    """Mock stats object for testing."""

    decode_fail: int = 0
    last_decode_error: str = ""
    last_failure_class: str = ""
    failure_count_header: int = 0
    failure_count_payload: int = 0
    failure_count_locator: int = 0
    failure_count_unknown: int = 0

    class _Lock:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    _lock = _Lock()


class TestWorkerExtractsErrorAttributes:
    """Test that worker correctly extracts DecodeError attributes."""

    def test_worker_extracts_gray4_header_error(self):
        """Worker should extract failure_class and context from Gray4HeaderDecodeError."""
        # Simulate decoder raising Gray4HeaderDecodeError
        exc = Gray4HeaderDecodeError(
            "bad v3 magic", context={"expected": "SAR3", "got": "XXXX"}
        )

        # Simulate worker exception handler
        error_msg = str(exc)
        failure_class = "unknown"
        context = None
        if isinstance(exc, DecodeError):
            failure_class = exc.failure_class
            context = exc.context

        assert error_msg == "bad v3 magic"
        assert failure_class == "header"
        assert context == {"expected": "SAR3", "got": "XXXX"}

    def test_worker_extracts_layered_body_error(self):
        """Worker should extract failure_class and context from LayeredBodyDecodeError."""
        exc = LayeredBodyDecodeError(
            "body RS decode failed", context={"rs_layer": "body", "erasures": 10}
        )

        error_msg = str(exc)
        failure_class = "unknown"
        context = None
        if isinstance(exc, DecodeError):
            failure_class = exc.failure_class
            context = exc.context

        assert error_msg == "body RS decode failed"
        assert failure_class == "payload"
        assert context == {"rs_layer": "body", "erasures": 10}

    def test_worker_handles_non_decode_error(self):
        """Worker should handle non-DecodeError exceptions gracefully."""
        exc = ValueError("some other error")

        error_msg = str(exc)
        failure_class = "unknown"
        context = None
        if isinstance(exc, DecodeError):
            failure_class = exc.failure_class
            context = exc.context

        assert error_msg == "some other error"
        assert failure_class == "unknown"
        assert context is None


class TestCoordinatorRecordsToProtocolCollector:
    """Test that coordinator correctly records error info to ProtocolCollector."""

    def test_coordinator_records_gray4_header_failure(self):
        """Coordinator should record Gray4 header failure to Gray4ProtocolCollector."""
        collector = Gray4ProtocolCollector()
        stats = MockStats()

        # Simulate DecodeCompletion from worker
        descriptor = FrameSlotDescriptor(
            slot_id=0,
            generation=1,
            capture_index=0,
            ts=0.0,
            width=1920,
            height=1080,
            fingerprint=b"",
        )
        completion = DecodeCompletion(
            descriptor=descriptor,
            worker_id=0,
            success=False,
            error="bad v3 magic",
            failure_class="header",
            context={"expected": "SAR3", "got": "XXXX"},
        )

        # Simulate coordinator handling failure
        error = getattr(completion, "error", "unknown error")
        failure_class = getattr(completion, "failure_class", "unknown")
        context = getattr(completion, "context", None)

        collector.on_decode_failure(
            error=error, failure_class=failure_class, context=context or {}
        )

        stats.decode_fail += 1
        stats.last_decode_error = error
        stats.last_failure_class = failure_class
        if failure_class == "header":
            stats.failure_count_header += 1

        # Verify collector
        data = collector.collect()
        assert data["gray4_last_failure_error"] == "bad v3 magic"
        assert data["gray4_last_failure_class"] == "header"
        assert data["gray4_last_failure_context"] == {
            "expected": "SAR3",
            "got": "XXXX",
        }

        # Verify stats
        assert stats.decode_fail == 1
        assert stats.last_decode_error == "bad v3 magic"
        assert stats.last_failure_class == "header"
        assert stats.failure_count_header == 1

    def test_coordinator_records_layered_body_failure(self):
        """Coordinator should record Layered body failure to LayeredProtocolCollector."""
        collector = LayeredProtocolCollector()
        stats = MockStats()

        descriptor = FrameSlotDescriptor(
            slot_id=0,
            generation=1,
            capture_index=0,
            ts=0.0,
            width=1920,
            height=1080,
            fingerprint=b"",
        )
        completion = DecodeCompletion(
            descriptor=descriptor,
            worker_id=0,
            success=False,
            error="body RS decode failed",
            failure_class="payload",
            context={"rs_layer": "body", "erasures": 10},
        )

        error = getattr(completion, "error", "unknown error")
        failure_class = getattr(completion, "failure_class", "unknown")
        context = getattr(completion, "context", None)

        collector.on_decode_failure(
            error=error, failure_class=failure_class, context=context
        )

        with stats._lock:
            stats.decode_fail += 1
            stats.last_decode_error = error
            stats.last_failure_class = failure_class
            if failure_class == "payload":
                stats.failure_count_payload += 1

        # Verify collector
        data = collector.collect()
        assert data["layered_last_failure_error"] == "body RS decode failed"
        assert data["layered_last_failure_class"] == "payload"
        assert data["layered_last_failure_context"] == {
            "rs_layer": "body",
            "erasures": 10,
        }

        # Verify stats
        assert stats.decode_fail == 1
        assert stats.last_decode_error == "body RS decode failed"
        assert stats.last_failure_class == "payload"
        assert stats.failure_count_payload == 1

    def test_coordinator_handles_multiple_failures(self):
        """Coordinator should record each failure (ProtocolCollector keeps only last one)."""
        collector = Gray4ProtocolCollector()
        stats = MockStats()

        descriptor = FrameSlotDescriptor(
            slot_id=0,
            generation=1,
            capture_index=0,
            ts=0.0,
            width=1920,
            height=1080,
            fingerprint=b"",
        )

        # First failure: header
        completion1 = DecodeCompletion(
            descriptor=descriptor,
            worker_id=0,
            success=False,
            error="bad magic",
            failure_class="header",
            context=None,
        )
        collector.on_decode_failure(
            error=completion1.error,
            failure_class=completion1.failure_class,
            context=completion1.context,
        )
        with stats._lock:
            stats.decode_fail += 1
            stats.failure_count_header += 1

        # Second failure: payload
        completion2 = DecodeCompletion(
            descriptor=descriptor,
            worker_id=0,
            success=False,
            error="CRC mismatch",
            failure_class="payload",
            context={"expected_crc": 0x1234, "got_crc": 0x5678},
        )
        collector.on_decode_failure(
            error=completion2.error,
            failure_class=completion2.failure_class,
            context=completion2.context,
        )
        with stats._lock:
            stats.decode_fail += 1
            stats.failure_count_payload += 1

        # Third failure: payload again
        completion3 = DecodeCompletion(
            descriptor=descriptor,
            worker_id=0,
            success=False,
            error="CRC mismatch",
            failure_class="payload",
            context=None,
        )
        collector.on_decode_failure(
            error=completion3.error,
            failure_class=completion3.failure_class,
            context=completion3.context,
        )
        with stats._lock:
            stats.decode_fail += 1
            stats.failure_count_payload += 1

        # Verify report only has last failure
        data = collector.collect()
        assert data["gray4_last_failure_error"] == "CRC mismatch"
        data = collector.collect()
        assert data["gray4_last_failure_class"] == "payload"
        # Context should not exist (last failure had no context)
        assert "gray4_last_failure_context" not in data

        # Verify stats has all counts
        assert stats.decode_fail == 3
        assert stats.failure_count_header == 1
        assert stats.failure_count_payload == 2


class TestEndToEndErrorFlow:
    """Test complete error flow: Decoder → Worker → Coordinator → Report."""

    def test_gray4_payload_error_end_to_end(self):
        """Test complete flow for Gray4 payload error."""
        # Step 1: Decoder raises Gray4PayloadDecodeError
        decoder_exc = Gray4PayloadDecodeError(
            "payload CRC mismatch", context={"expected_crc": 0x1234, "got_crc": 0x5678}
        )

        # Step 2: Worker catches exception and extracts attributes
        error_msg = str(decoder_exc)
        failure_class = "unknown"
        context = None
        if isinstance(decoder_exc, DecodeError):
            failure_class = decoder_exc.failure_class
            context = decoder_exc.context

        # Step 3: Worker creates DecodeCompletion
        descriptor = FrameSlotDescriptor(
            slot_id=0,
            generation=1,
            capture_index=0,
            ts=0.0,
            width=1920,
            height=1080,
            fingerprint=b"",
        )
        completion = DecodeCompletion(
            descriptor=descriptor,
            worker_id=0,
            success=False,
            error=error_msg,
            failure_class=failure_class,
            context=context,
        )

        # Step 4: Coordinator receives completion and updates report
        collector = Gray4ProtocolCollector()
        stats = MockStats()

        collector.on_decode_failure(
            error=completion.error,
            failure_class=completion.failure_class,
            context=completion.context,
        )

        with stats._lock:
            stats.decode_fail += 1
            stats.last_decode_error = completion.error
            stats.last_failure_class = completion.failure_class
            if completion.failure_class == "payload":
                stats.failure_count_payload += 1

        # Step 5: Verify final state
        data = collector.collect()
        assert data["gray4_last_failure_error"] == "payload CRC mismatch"
        data = collector.collect()
        assert data["gray4_last_failure_class"] == "payload"
        data = collector.collect()
        assert data["gray4_last_failure_context"] == {
            "expected_crc": 0x1234,
            "got_crc": 0x5678,
        }

        assert stats.decode_fail == 1
        assert stats.last_decode_error == "payload CRC mismatch"
        assert stats.last_failure_class == "payload"
        assert stats.failure_count_payload == 1

    def test_layered_bootstrap_error_end_to_end(self):
        """Test complete flow for Layered bootstrap error."""
        # Step 1: Decoder raises LayeredBootstrapDecodeError
        decoder_exc = LayeredBootstrapDecodeError(
            "bootstrap RS decode failed",
            context={"rs_layer": "bootstrap", "correctable": False},
        )

        # Step 2: Worker catches and extracts
        error_msg = str(decoder_exc)
        failure_class = "unknown"
        context = None
        if isinstance(decoder_exc, DecodeError):
            failure_class = decoder_exc.failure_class
            context = decoder_exc.context

        # Step 3: Worker creates DecodeCompletion
        descriptor = FrameSlotDescriptor(
            slot_id=0,
            generation=1,
            capture_index=0,
            ts=0.0,
            width=1920,
            height=1080,
            fingerprint=b"",
        )
        completion = DecodeCompletion(
            descriptor=descriptor,
            worker_id=0,
            success=False,
            error=error_msg,
            failure_class=failure_class,
            context=context,
        )

        # Step 4: Coordinator updates report
        collector = LayeredProtocolCollector()
        stats = MockStats()

        collector.on_decode_failure(
            error=completion.error,
            failure_class=completion.failure_class,
            context=completion.context,
        )

        with stats._lock:
            stats.decode_fail += 1
            stats.last_decode_error = completion.error
            stats.last_failure_class = completion.failure_class
            if completion.failure_class == "header":
                stats.failure_count_header += 1

        # Step 5: Verify final state
        data = collector.collect()
        assert data["layered_last_failure_error"] == "bootstrap RS decode failed"
        data = collector.collect()
        assert data["layered_last_failure_class"] == "header"
        data = collector.collect()
        assert data["layered_last_failure_context"] == {
            "rs_layer": "bootstrap",
            "correctable": False,
        }

        assert stats.decode_fail == 1
        assert stats.last_decode_error == "bootstrap RS decode failed"
        assert stats.last_failure_class == "header"
        assert stats.failure_count_header == 1
