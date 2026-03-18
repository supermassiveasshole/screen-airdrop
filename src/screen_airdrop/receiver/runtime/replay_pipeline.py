"""Replay pipeline for offline frame decoding.

This pipeline is designed for replay mode where frames are read from disk
rather than captured from screen. It's much simpler than ScreenLiveRuntime:
- No screen capture
- No preprocessing
- No ROI detection
- Just direct frame decoding in a single thread
"""

import threading
import time
from typing import Any, Dict, Optional

from screen_airdrop.common.control_plane import control_kind_from_wire_chunk_id
from screen_airdrop.common.protocol_basic import FRAME_DATA
from screen_airdrop.receiver.assembler import ChunkAssembler
from screen_airdrop.receiver.protocol_decoder_factory import create_protocol_decoder
from screen_airdrop.receiver.protocol_observability import (
    _classify_gray4_decode_failure,
    make_protocol_report_adapter,
)
from screen_airdrop.receiver.runtime.base_pipeline import BasePipeline
from screen_airdrop.receiver.runtime.stats import ScreenLiveRuntimeStats


class ReplayPipeline(BasePipeline):
    """Simple pipeline for replaying captured frames.

    This pipeline reads frames from a FrameReplaySource and decodes them
    directly in a single thread. No screen capture, no preprocessing, no ROI
    detection - just pure decoding for testing and benchmarking.
    """

    def __init__(
        self,
        frame_source,  # FrameReplaySource instance
        assembler: ChunkAssembler,
        protocol: str = "basic",
        grid_w: int = 160,
        grid_h: int = 96,
        guard_band: int = 2,
        corner_size: int = 9,
        locator_engine: str = "auto",
        locator_confidence_threshold: float = 0.55,
    ):
        super().__init__(protocol=protocol)

        self.frame_source = frame_source
        self.assembler = assembler
        self.stats = ScreenLiveRuntimeStats(protocol=protocol, prep_mode="none")
        self.stats.protocol_report_adapter = make_protocol_report_adapter(protocol)

        # Create report collector
        self.report_collector = self._create_report_collector(
            stats=self.stats,
            assembler=assembler,
        )

        # Threading primitives
        self._stop_event = threading.Event()
        self.done_event = threading.Event()
        self._error: Optional[Exception] = None

        # Create protocol decoder using factory
        self._decoder = create_protocol_decoder(
            protocol=protocol,
            grid_w=grid_w,
            grid_h=grid_h,
            guard_band=guard_band,
            corner_size=corner_size,
            locator_engine=locator_engine,
            locator_confidence_threshold=locator_confidence_threshold,
        )

        # Main processing thread
        self._main_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the pipeline."""
        self._main_thread = threading.Thread(target=self._run, daemon=True)
        self._main_thread.start()

    def _run(self) -> None:
        """Main processing loop - decode frames sequentially."""
        try:
            for frame in self.frame_source.iter_frames():
                if self._stop_event.is_set():
                    break

                # Update captured count
                with self.stats._lock:
                    self.stats.captured += 1

                # Decode frame
                try:
                    decoded = self._decoder.decode_frame(
                        frame=frame,
                        detect_mode="full",
                        forced_roi=None,
                    )
                    header = decoded.frame_header
                    payload = decoded.payload
                    meta = decoded.meta

                    # Update stats
                    with self.stats._lock:
                        self.stats.decode_ok += 1
                        decoded_ts = time.time()
                        if self.stats.first_valid_frame_ts is None:
                            self.stats.first_valid_frame_ts = decoded_ts
                        if int(header.frame_type) == int(FRAME_DATA) and self.stats.first_data_frame_ts is None:
                            self.stats.first_data_frame_ts = decoded_ts

                    # Update report collector
                    if self.report_collector:
                        self.report_collector.on_decode_success(meta)

                    # Process frame based on type
                    if header.frame_type == FRAME_DATA:
                        control_kind = control_kind_from_wire_chunk_id(header.chunk_id)
                        if control_kind is not None:
                            # Control frame
                            with self.stats._lock:
                                if self.stats.first_new_chunk_ts is None:
                                    self.stats.startup_control_frames_decoded += 1
                            try:
                                self.assembler.add_control(control_kind, payload)
                            except Exception:
                                pass
                        elif header.chunk_id > 0:
                            # Data chunk
                            is_new_chunk = header.chunk_id not in self.assembler.chunks
                            self.assembler.add(header.chunk_id, payload)
                            with self.stats._lock:
                                if is_new_chunk:
                                    self.stats.decoded_new_chunks += 1
                                    self.stats.assembled += 1
                                    self.stats.assembled_bytes += len(payload)
                                    if self.stats.first_new_chunk_ts is None:
                                        self.stats.first_new_chunk_ts = decoded_ts
                                else:
                                    self.stats.decoded_duplicate_chunks += 1
                    else:
                        # Sync frame
                        with self.stats._lock:
                            if self.stats.first_new_chunk_ts is None:
                                self.stats.startup_sync_frames_decoded += 1

                    # Check if complete
                    if self.assembler.complete():
                        self.done_event.set()
                        break

                except Exception as exc:
                    # Decode failure
                    with self.stats._lock:
                        self.stats.decode_fail += 1
                        self.stats.decode_exceptions += 1
                        self.stats.last_decode_error = str(exc)

                        # Classify failure
                        failure_class = _classify_gray4_decode_failure(str(exc))
                        self.stats.last_failure_class = failure_class
                        if failure_class == "header":
                            self.stats.failure_count_header += 1
                        elif failure_class == "payload":
                            self.stats.failure_count_payload += 1
                        elif failure_class == "locator":
                            self.stats.failure_count_locator += 1
                        elif failure_class:
                            self.stats.failure_count_unknown += 1

                    # Update report collector
                    if self.report_collector:
                        self.report_collector.on_decode_failure(
                            error=str(exc),
                            failure_class=failure_class,
                            context={},
                        )

        except Exception as exc:
            self._error = exc

        finally:
            self.done_event.set()

    def stop(self) -> None:
        """Stop the pipeline."""
        self._stop_event.set()

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Wait for pipeline to complete."""
        return self.done_event.wait(timeout=timeout)

    def join(self, timeout: float = 10.0) -> None:
        """Stop and clean up pipeline resources."""
        self.stop()

        # Wait for main thread
        if self._main_thread:
            self._main_thread.join(timeout=timeout)

    def check_errors(self) -> None:
        """Check and raise pipeline errors."""
        if self._error:
            raise self._error

    def snapshot(self) -> Dict[str, Any]:
        """Get pipeline statistics snapshot."""
        return self.stats.snapshot()
