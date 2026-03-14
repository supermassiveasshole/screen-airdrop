"""Unit tests for the async receiver pipeline."""

from __future__ import annotations

import queue
import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np

from screen_airdrop.common.protocol_basic import FRAME_DATA, FrameHeaderBasic
from screen_airdrop.common.protocol_interface import DecodedFrame
from screen_airdrop.receiver.assembler import ChunkAssembler
from screen_airdrop.receiver.decoder_basic import DecodeMetaBasic
from screen_airdrop.receiver.pipeline import (
    AssemblerThread,
    DecodeResult,
    DecodeWorker,
    PipelineStats,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_capture(frames):
    """Build a mock ScreenCapture that yields numpy arrays."""
    cap = MagicMock()
    cap.monitor_index = 1
    cap.window_title = None
    cap.region = None
    cap.active_region = None
    cap._mss_mod = None
    return cap


def _make_black_frame(h=100, w=100):
    return np.zeros((h, w, 3), dtype=np.uint8)


def _make_meta(
    det_bbox=(20, 10, 60, 40),
    confidence=0.9,
    elapsed_ms=10.0,
    legacy_used=False,
    mask_id=3,
    grid_size="160x96",
):
    return DecodeMetaBasic(
        protocol_version_used=31,
        locator_engine="auto",
        confidence=confidence,
        fail_reason="",
        elapsed_ms=elapsed_ms,
        legacy_used=legacy_used,
        homography_rmse=1.25,
        rs_corrected_symbols=2,
        crc_ok=True,
        mask_id=mask_id,
        grid_size=grid_size,
        det_bbox=det_bbox,
        decode_attempts=2,
        det_confidence=confidence,
        new_fail_reason="",
        new_elapsed_ms=elapsed_ms,
        legacy_elapsed_ms=0.0,
        locator_debug_artifacts={"path": "kept"},
        locator_warped_preview=None,
    )


# ---------------------------------------------------------------------------
# PipelineStats
# ---------------------------------------------------------------------------


class TestPipelineStats:
    def test_snapshot_returns_copy(self):
        stats = PipelineStats()
        with stats._lock:
            stats.captured = 5
            stats.capture_grab_ops = 2
        snap = stats.snapshot()
        assert snap["captured"] == 5
        assert snap["capture_grab_ops"] == 2
        # Mutating snap doesn't affect stats
        snap["captured"] = 99
        assert stats.snapshot()["captured"] == 5

    def test_concurrent_increments(self):
        stats = PipelineStats()

        def worker():
            for _ in range(1000):
                with stats._lock:
                    stats.captured += 1

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert stats.captured == 4000


# ---------------------------------------------------------------------------
# CaptureThread – queue-full drop behaviour
# ---------------------------------------------------------------------------


class TestCaptureThreadQueueDrop:
    def test_drops_oldest_when_full(self):
        """When the frame queue is full, CaptureThread should evict the oldest
        entry so the queue always contains fresh frames."""
        fq = queue.Queue(maxsize=4)
        stats = PipelineStats()

        # Pre-fill queue with sentinel frames
        sentinel = _make_black_frame()
        sentinel[:] = 10  # value 10 = "old"
        for _ in range(4):
            fq.put(sentinel.copy())

        # Simulate one push cycle from CaptureThread
        new_frame = _make_black_frame()
        new_frame[:] = 99  # value 99 = "new"

        if fq.full():
            try:
                fq.get_nowait()
                with stats._lock:
                    stats.dropped_queue_full += 1
            except queue.Empty:
                pass
        fq.put_nowait(new_frame)

        assert fq.qsize() == 4
        assert stats.dropped_queue_full == 1
        # New frame should be present in the queue
        frames_in_queue = []
        while not fq.empty():
            frames_in_queue.append(fq.get_nowait())
        assert any(f[0, 0, 0] == 99 for f in frames_in_queue), "new frame must be in queue"


# ---------------------------------------------------------------------------
# AssemblerThread – concurrent results, completion signalling
# ---------------------------------------------------------------------------


class TestAssemblerThread:
    def _make_result(self, chunk_id, payload=None):
        meta = MagicMock()
        return DecodeResult(
            chunk_id=chunk_id,
            payload=payload or b"\x00" * 8,
            frame_id=chunk_id,
            frame_type=int(FRAME_DATA),
            meta=meta,
        )

    def test_signals_done_when_complete(self):
        from screen_airdrop.common.manifest import Manifest

        assembler = ChunkAssembler()
        # Manually inject a manifest with total_chunks=3
        manifest = MagicMock(spec=Manifest)
        manifest.total_chunks = 3
        assembler.manifest = manifest

        rq = queue.Queue()
        done = threading.Event()
        stop = threading.Event()
        stats = PipelineStats()

        thread = AssemblerThread(
            result_queue=rq,
            assembler=assembler,
            done_event=done,
            stop_event=stop,
            stats=stats,
        )
        thread.start()

        for cid in range(1, 4):
            rq.put(self._make_result(cid))

        assert done.wait(timeout=2.0), "done_event should be set after all chunks received"
        stop.set()
        thread.join(timeout=2.0)

    def test_deduplicates_chunks(self):
        from screen_airdrop.common.manifest import Manifest

        assembler = ChunkAssembler()
        manifest = MagicMock(spec=Manifest)
        manifest.total_chunks = 2
        assembler.manifest = manifest

        rq = queue.Queue()
        done = threading.Event()
        stop = threading.Event()
        stats = PipelineStats()

        thread = AssemblerThread(
            result_queue=rq,
            assembler=assembler,
            done_event=done,
            stop_event=stop,
            stats=stats,
        )
        thread.start()

        # Send chunk 1 twice, then chunk 2 once
        rq.put(self._make_result(1, b"aaa"))
        rq.put(self._make_result(1, b"bbb"))  # duplicate
        rq.put(self._make_result(2, b"ccc"))

        assert done.wait(timeout=2.0)
        stop.set()
        thread.join(timeout=2.0)

        # assembler should have stored original payload, not duplicate
        assert assembler.chunks[1] == b"aaa"
        assert assembler._received_count == 2  # only 2 unique chunks
        assert stats.assembled == 2
        assert stats.assembled_bytes == len(b"aaa") + len(b"ccc")

    def test_ignores_non_data_chunk_zero_without_crashing(self):
        assembler = ChunkAssembler()
        rq = queue.Queue()
        done = threading.Event()
        stop = threading.Event()
        stats = PipelineStats()

        thread = AssemblerThread(
            result_queue=rq,
            assembler=assembler,
            done_event=done,
            stop_event=stop,
            stats=stats,
        )
        thread.start()

        meta = MagicMock()
        # END/SYNC-like frame: chunk_id=0 but not DATA.
        rq.put(
            DecodeResult(
                chunk_id=0,
                payload=b"",
                frame_id=0,
                frame_type=0,
                meta=meta,
            )
        )

        time.sleep(0.1)
        stop.set()
        thread.join(timeout=2.0)
        assert thread.error is None


# ---------------------------------------------------------------------------
# ChunkAssembler O(1) paths
# ---------------------------------------------------------------------------


class TestChunkAssemblerO1:
    def test_complete_o1(self):
        from screen_airdrop.common.manifest import Manifest

        asm = ChunkAssembler()
        manifest = MagicMock(spec=Manifest)
        manifest.total_chunks = 3
        asm.manifest = manifest

        assert not asm.complete()
        asm.add(1, b"a")
        asm.add(2, b"b")
        assert not asm.complete()
        asm.add(3, b"c")
        assert asm.complete()

    def test_missing_count_o1(self):
        from screen_airdrop.common.manifest import Manifest

        asm = ChunkAssembler()
        assert asm.missing_count() is None

        manifest = MagicMock(spec=Manifest)
        manifest.total_chunks = 5
        asm.manifest = manifest

        assert asm.missing_count() == 5
        asm.add(1, b"x")
        assert asm.missing_count() == 4
        asm.add(1, b"x")  # duplicate – count must not change
        assert asm.missing_count() == 4

    def test_received_count_tracks_unique(self):
        asm = ChunkAssembler()
        asm.add(1, b"a")
        asm.add(1, b"b")  # duplicate
        asm.add(2, b"c")
        assert asm._received_count == 2


class TestDecodeWorker:
    def test_uses_initial_roi_with_track_mode(self):
        fq = queue.Queue()
        rq = queue.Queue()
        stop = threading.Event()
        stats = PipelineStats()
        frame = _make_black_frame(120, 160)
        fq.put(frame)

        calls = []

        def _fake_decode_frame(**kwargs):
            calls.append(kwargs)
            stop.set()
            header = FrameHeaderBasic.make(
                frame_type=FRAME_DATA,
                session_id=1,
                epoch_id=0,
                frame_id=1,
                total_frames=10,
                chunk_id=1,
                payload=b"ok",
            )
            return DecodedFrame(frame_header=header, payload=b"ok", meta=_make_meta())

        with patch(
            "screen_airdrop.receiver.protocol_adapter_basic.BasicProtocolDecoder.decode_frame",
            side_effect=_fake_decode_frame,
        ):
            worker = DecodeWorker(
                worker_id=0,
                frame_queue=fq,
                result_queue=rq,
                stop_event=stop,
                stats=stats,
                initial_search_roi=(1, 2, 50, 50),
            )
            worker.start()
            worker.join(timeout=2.0)

        assert len(calls) == 1
        assert calls[0]["detect_mode"] == "track"
        assert calls[0]["forced_roi"] == (1, 2, 50, 50)
        assert stats.decode_ok == 1
        assert rq.qsize() == 1
        result = rq.get_nowait()
        assert result.meta.homography_rmse == 1.25
        assert result.meta.rs_corrected_symbols == 2
        assert result.meta.locator_debug_artifacts == {"path": "kept"}

    def test_result_queue_full_is_counted(self):
        fq = queue.Queue()
        rq = queue.Queue(maxsize=1)
        stop = threading.Event()
        stats = PipelineStats()
        fq.put(_make_black_frame(100, 100))
        rq.put(object())  # pre-fill to force Full on put

        def _fake_decode_frame(**kwargs):
            _ = kwargs
            stop.set()
            header = FrameHeaderBasic.make(
                frame_type=FRAME_DATA,
                session_id=1,
                epoch_id=0,
                frame_id=1,
                total_frames=10,
                chunk_id=1,
                payload=b"ok",
            )
            return DecodedFrame(
                frame_header=header,
                payload=b"ok",
                meta=_make_meta(det_bbox=(10, 10, 40, 40)),
            )

        with patch(
            "screen_airdrop.receiver.protocol_adapter_basic.BasicProtocolDecoder.decode_frame",
            side_effect=_fake_decode_frame,
        ):
            worker = DecodeWorker(
                worker_id=0,
                frame_queue=fq,
                result_queue=rq,
                stop_event=stop,
                stats=stats,
            )
            worker.start()
            worker.join(timeout=2.0)

        assert stats.decode_ok == 0
        assert stats.dropped_result_queue_full == 1

    def test_decode_failure_restores_initial_roi(self):
        fq = queue.Queue()
        rq = queue.Queue()
        stop = threading.Event()
        stats = PipelineStats()
        fq.put(_make_black_frame(100, 100))

        def _fake_decode_frame(**kwargs):
            _ = kwargs
            stop.set()
            raise ValueError("decode failed")

        with patch(
            "screen_airdrop.receiver.protocol_adapter_basic.BasicProtocolDecoder.decode_frame",
            side_effect=_fake_decode_frame,
        ):
            worker = DecodeWorker(
                worker_id=0,
                frame_queue=fq,
                result_queue=rq,
                stop_event=stop,
                stats=stats,
                initial_search_roi=(5, 6, 70, 70),
            )
            worker.start()
            worker.join(timeout=2.0)

        assert stats.decode_fail == 1
        assert stats.decode_exceptions == 1
        assert worker._track_roi == (5, 6, 70, 70)
