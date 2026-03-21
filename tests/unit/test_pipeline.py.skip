# pyright: reportAttributeAccessIssue=false, reportIndexIssue=false, reportOperatorIssue=false
"""Unit tests for the async receiver pipeline."""

from __future__ import annotations

import queue
import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np

from screen_airdrop.common.control_plane import (
    CONTROL_KIND_GENERATION,
    CONTROL_KIND_LAYOUT,
    CONTROL_KIND_MANIFEST,
    CONTROL_KIND_SESSION,
    CONTROL_WIRE_CHUNK_IDS,
    encode_generation_control,
    encode_layout_bootstrap,
    encode_session_bootstrap,
)
from screen_airdrop.common.protocol_basic import FRAME_DATA, FrameHeaderBasic
from screen_airdrop.common.protocol_interface import DecodedFrame
from screen_airdrop.receiver.assembler import ChunkAssembler
from screen_airdrop.receiver.decoder_basic import DecodeMetaBasic
from screen_airdrop.receiver.pipeline import (
    AssemblerThread,
    DecodeResult,
    DecodeWorker,
    PipelineStats,
    _create_shared_frame,
    _fingerprint_diff,
    _fingerprint_from_bgra,
    _release_shared_frame,
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


class TestPipelineHelpers:
    def test_fingerprint_detects_identical_and_changed_frames(self):
        frame = np.zeros((64, 64, 4), dtype=np.uint8)
        fp1 = _fingerprint_from_bgra(frame)
        fp2 = _fingerprint_from_bgra(frame.copy())
        assert _fingerprint_diff(fp1, fp2) == 0.0

        frame[10:20, 10:20, 2] = 255
        fp3 = _fingerprint_from_bgra(frame)
        assert _fingerprint_diff(fp1, fp3) > 0.0

    def test_shared_frame_lifecycle_roundtrip(self):
        frame = np.arange(4 * 4 * 3, dtype=np.uint8).reshape(4, 4, 3)
        fake_instances = []

        class _FakeShm:
            def __init__(self, *, create=False, size=0, name=None):
                self.name = "fake-shm" if create else str(name)
                self.buf = bytearray(size if create else frame.nbytes)
                self.closed = False
                self.unlinked = False
                fake_instances.append(self)

            def close(self):
                self.closed = True

            def unlink(self):
                self.unlinked = True

        with patch("screen_airdrop.receiver.pipeline.shared_memory.SharedMemory", side_effect=_FakeShm):
            shm_name, shm_bytes = _create_shared_frame(frame)
            assert shm_name == "fake-shm"
            assert shm_bytes == frame.nbytes
            _release_shared_frame(shm_name)

        assert fake_instances[0].closed is True
        assert fake_instances[-1].unlinked is True


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

    def test_capture_dump_writes_replay_frame(self, tmp_path):
        from screen_airdrop.receiver.pipeline import CaptureThread

        fq = queue.Queue(maxsize=4)
        stats = PipelineStats()
        stop = threading.Event()
        dump_dir = tmp_path / "capture-dump"
        dump_dir.mkdir()
        frame = _make_black_frame()
        frame[:] = 77

        thread = CaptureThread(
            capture=MagicMock(),
            frame_queue=fq,
            stop_event=stop,
            stats=stats,
            dump_dir=str(dump_dir),
            dump_max_frames=2,
        )
        thread._dump_dir = str(dump_dir)
        thread._dump_max_frames = 2
        thread._dump_written = 0

        dump_path = dump_dir / "000000.npy"
        np.save(dump_path, frame)
        loaded = np.load(dump_path)

        assert loaded.shape == frame.shape
        assert int(loaded[0, 0, 0]) == 77


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


def test_chunk_assembler_accepts_explicit_manifest_control():
    from screen_airdrop.common.manifest import Manifest

    manifest = Manifest(
        protocol_version=1,
        session_id=123,
        created_at="2026-03-14T00:00:00Z",
        input_root_name="payload.bin",
        pack="tar",
        compress="none",
        chunk_size=16,
        total_chunks=2,
        payload_size=5,
        payload_sha256="abc",
        entries=[],
    )

    asm = ChunkAssembler()
    asm.add_control(CONTROL_KIND_MANIFEST, manifest.to_json_bytes())

    assert asm.manifest is not None
    assert asm.manifest.session_id == 123
    assert asm.manifest.total_chunks == 2


def test_chunk_assembler_accepts_layout_bootstrap_control():
    asm = ChunkAssembler()
    asm.add_control(
        CONTROL_KIND_LAYOUT,
        encode_layout_bootstrap(
            {
                "protocol": "gray4",
                "protocol_version": "4.1",
                "frame_w": 170,
                "frame_h": 106,
                "grid_w": 160,
                "grid_h": 96,
                "bits_per_module": 2,
                "guard_band": 1,
                "quiet_zone": 4,
                "finder_size": 7,
                "ecc_level": "L",
                "frame_payload_cap": 3754,
                "effective_chunk_size": 3378,
                "module_grid": "160x96",
            }
        ),
    )

    assert asm.layout_info is not None
    assert asm.layout_info["protocol"] == "gray4"
    assert asm.layout_info["bits_per_module"] == 2


def test_chunk_assembler_accepts_session_bootstrap_control():
    asm = ChunkAssembler()
    asm.add_control(
        CONTROL_KIND_SESSION,
        encode_session_bootstrap(
            {
                "session_id": 456,
                "protocol": "gray4",
                "protocol_version": 4,
                "created_at": "2026-03-14T00:00:00Z",
                "input_root_name": "paper.pdf",
                "pack": "tar",
                "compress": "gzip",
                "window_name": "screen-airdrop",
            }
        ),
    )

    assert asm.session_info is not None
    assert asm.session_info["session_id"] == 456
    assert asm.session_info["protocol"] == "gray4"


def test_chunk_assembler_accepts_generation_control():
    asm = ChunkAssembler()
    asm.add_control(
        CONTROL_KIND_GENERATION,
        encode_generation_control(
            {
                "generation_id": 7,
                "total_frames": 42,
                "payload_chunk_count": 31,
                "effective_chunk_size": 2048,
                "protocol": "gray4",
            }
        ),
    )

    assert asm.generation_info is not None
    assert asm.generation_info["generation_id"] == 7
    assert asm.generations[7]["payload_chunk_count"] == 31


def test_assembler_thread_does_not_count_layout_control_as_data():
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

    rq.put(
        DecodeResult(
            chunk_id=CONTROL_WIRE_CHUNK_IDS[CONTROL_KIND_LAYOUT],
            payload=encode_layout_bootstrap(
                {
                    "protocol": "compact",
                    "protocol_version": "4.0",
                    "frame_w": 170,
                    "frame_h": 106,
                    "grid_w": 160,
                    "grid_h": 96,
                    "bits_per_module": 1,
                    "guard_band": 1,
                    "quiet_zone": 4,
                    "finder_size": 7,
                    "ecc_level": "Q",
                    "frame_payload_cap": 2048,
                    "effective_chunk_size": 1834,
                    "module_grid": "160x96",
                }
            ),
            frame_id=0,
            frame_type=int(FRAME_DATA),
            meta=MagicMock(),
        )
    )

    time.sleep(0.1)
    stop.set()
    thread.join(timeout=2.0)

    assert thread.error is None
    assert assembler.layout_info is not None
    assert stats.assembled == 0
    assert stats.assembled_bytes == 0


def test_assembler_thread_accepts_session_control_without_counting_data():
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

    rq.put(
        DecodeResult(
            chunk_id=CONTROL_WIRE_CHUNK_IDS[CONTROL_KIND_SESSION],
            payload=encode_session_bootstrap(
                {
                    "session_id": 789,
                    "protocol": "compact",
                    "protocol_version": 4,
                    "created_at": "2026-03-14T00:00:00Z",
                    "input_root_name": "sample.bin",
                    "pack": "tar",
                    "compress": "none",
                    "window_name": "screen-airdrop",
                }
            ),
            frame_id=0,
            frame_type=int(FRAME_DATA),
            meta=MagicMock(),
        )
    )

    time.sleep(0.1)
    stop.set()
    thread.join(timeout=2.0)

    assert thread.error is None
    assert assembler.session_info is not None
    assert assembler.session_info["session_id"] == 789
    assert stats.assembled == 0
    assert stats.assembled_bytes == 0


def test_assembler_thread_accepts_generation_control_without_counting_data():
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

    rq.put(
        DecodeResult(
            chunk_id=CONTROL_WIRE_CHUNK_IDS[CONTROL_KIND_GENERATION],
            payload=encode_generation_control(
                {
                    "generation_id": 3,
                    "total_frames": 20,
                    "payload_chunk_count": 12,
                    "effective_chunk_size": 1834,
                    "protocol": "compact",
                }
            ),
            frame_id=0,
            frame_type=int(FRAME_DATA),
            meta=MagicMock(),
        )
    )

    time.sleep(0.1)
    stop.set()
    thread.join(timeout=2.0)

    assert thread.error is None
    assert assembler.generation_info is not None
    assert assembler.generation_info["generation_id"] == 3
    assert stats.assembled == 0
    assert stats.assembled_bytes == 0


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

    def test_missing_chunk_ids_returns_first_missing_chunks(self):
        from screen_airdrop.common.manifest import Manifest

        asm = ChunkAssembler()
        manifest = MagicMock(spec=Manifest)
        manifest.total_chunks = 6
        asm.manifest = manifest
        asm.add(2, b"b")
        asm.add(5, b"e")

        assert asm.missing_chunk_ids(limit=3) == [1, 3, 4]

    def test_received_count_tracks_unique(self):
        asm = ChunkAssembler()
        asm.add(1, b"a")
        asm.add(1, b"b")  # duplicate
        asm.add(2, b"c")
        assert asm._received_count == 2


class TestDecodeWorker:
    def test_uses_initial_roi_with_track_mode(self):
        fq = queue.Queue()
        release_q = queue.Queue()
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
                release_queue=release_q,
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
        release_q = queue.Queue()
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
                release_queue=release_q,
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
        release_q = queue.Queue()
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
                release_queue=release_q,
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

    def test_lock_state_transitions_to_locked_after_success(self):
        fq = queue.Queue()
        release_q = queue.Queue()
        rq = queue.Queue()
        stop = threading.Event()
        stats = PipelineStats()
        fq.put(_make_black_frame(100, 100))

        def _fake_decode_frame(**kwargs):
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
                release_queue=release_q,
                result_queue=rq,
                stop_event=stop,
                stats=stats,
            )
            worker.start()
            worker.join(timeout=2.0)

        snap = stats.snapshot()
        assert worker._lock_state == "locked"
        assert snap["lock_acquire_to_locked"] == 1
        assert snap["time_to_first_valid_frame_s"] >= 0.0
        assert snap["time_to_first_data_frame_s"] >= 0.0

    def test_lock_state_reacquires_after_five_failures(self):
        fq = queue.Queue()
        release_q = queue.Queue()
        rq = queue.Queue()
        stop = threading.Event()
        stats = PipelineStats()
        for _ in range(6):
            fq.put(_make_black_frame(100, 100))

        calls = {"count": 0}

        def _fake_decode_frame(**kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
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
            if calls["count"] >= 6:
                stop.set()
            raise ValueError("decode failed")

        with patch(
            "screen_airdrop.receiver.protocol_adapter_basic.BasicProtocolDecoder.decode_frame",
            side_effect=_fake_decode_frame,
        ):
            worker = DecodeWorker(
                worker_id=0,
                frame_queue=fq,
                release_queue=release_q,
                result_queue=rq,
                stop_event=stop,
                stats=stats,
                initial_search_roi=(5, 6, 70, 70),
            )
            worker.start()
            worker.join(timeout=2.0)

        snap = stats.snapshot()
        assert worker._lock_state == "acquire"
        assert worker._track_roi == (0, 0, 74, 74)
        assert snap["lock_locked_to_acquire"] == 1
        assert snap["locked_decode_fail_streak_max"] == 5

    def test_layered_locked_state_prefers_geometry_reuse(self):
        fq = queue.Queue()
        release_q = queue.Queue()
        rq = queue.Queue()
        stop = threading.Event()
        stats = PipelineStats()
        fq.put(_make_black_frame(100, 100))
        fq.put(_make_black_frame(100, 100))

        calls = {"decode_frame": 0, "decode_frame_with_geometry": 0}

        def _make_layered_result(frame_id, chunk_id, *, geometry_reused):
            header = FrameHeaderBasic.make(
                frame_type=FRAME_DATA,
                session_id=1,
                epoch_id=0,
                frame_id=frame_id,
                total_frames=10,
                chunk_id=chunk_id,
                payload=b"ok",
            )
            meta = _make_meta(det_bbox=(10, 10, 40, 40))
            meta.quad_src = np.zeros((4, 2), dtype=np.float32)
            meta.homography = np.eye(3, dtype=np.float32)
            meta.homography_inv = np.eye(3, dtype=np.float32)
            meta.geometry_reused = geometry_reused
            meta.locator_warped_preview = np.zeros((10, 10, 3), dtype=np.uint8)
            return DecodedFrame(frame_header=header, payload=b"ok", meta=meta)

        def _fake_decode_frame(**kwargs):
            calls["decode_frame"] += 1
            _ = kwargs
            return _make_layered_result(1, 1, geometry_reused=False)

        def _fake_decode_frame_with_geometry(**kwargs):
            calls["decode_frame_with_geometry"] += 1
            _ = kwargs
            stop.set()
            return _make_layered_result(2, 2, geometry_reused=True)

        with patch(
            "screen_airdrop.receiver.protocol_adapter_layered.LayeredProtocolDecoder.decode_frame",
            side_effect=_fake_decode_frame,
        ), patch(
            "screen_airdrop.receiver.protocol_adapter_layered.LayeredProtocolDecoder.decode_frame_with_geometry",
            side_effect=_fake_decode_frame_with_geometry,
        ):
            worker = DecodeWorker(
                worker_id=0,
                frame_queue=fq,
                release_queue=release_q,
                result_queue=rq,
                stop_event=stop,
                stats=stats,
                protocol="layered",
            )
            worker.start()
            worker.join(timeout=2.0)

        snap = stats.snapshot()
        assert calls["decode_frame"] == 1
        assert calls["decode_frame_with_geometry"] == 1
        assert snap["lock_decode_mode_counts"]["geometry_reuse"] == 1
        assert snap["geometry_reuse_success_count"] == 1
        assert snap["reacquire_success_count"] == 1

    def test_layered_geometry_reuse_only_reacquires_after_five_failures(self):
        fq = queue.Queue()
        release_q = queue.Queue()
        rq = queue.Queue()
        stop = threading.Event()
        stats = PipelineStats()
        for _ in range(7):
            fq.put(_make_black_frame(100, 100))

        calls = {"decode_frame": 0, "decode_frame_with_geometry": 0}

        def _make_layered_result():
            header = FrameHeaderBasic.make(
                frame_type=FRAME_DATA,
                session_id=1,
                epoch_id=0,
                frame_id=1,
                total_frames=10,
                chunk_id=1,
                payload=b"ok",
            )
            meta = _make_meta(det_bbox=(10, 10, 40, 40))
            meta.quad_src = np.zeros((4, 2), dtype=np.float32)
            meta.homography = np.eye(3, dtype=np.float32)
            meta.homography_inv = np.eye(3, dtype=np.float32)
            meta.geometry_reused = False
            meta.locator_warped_preview = np.zeros((10, 10, 3), dtype=np.uint8)
            return DecodedFrame(frame_header=header, payload=b"ok", meta=meta)

        def _fake_decode_frame(**kwargs):
            calls["decode_frame"] += 1
            if calls["decode_frame"] >= 2:
                stop.set()
            return _make_layered_result()

        def _fake_decode_frame_with_geometry(**kwargs):
            calls["decode_frame_with_geometry"] += 1
            _ = kwargs
            raise ValueError("bootstrap rs decode failed")

        with patch(
            "screen_airdrop.receiver.protocol_adapter_layered.LayeredProtocolDecoder.decode_frame",
            side_effect=_fake_decode_frame,
        ), patch(
            "screen_airdrop.receiver.protocol_adapter_layered.LayeredProtocolDecoder.decode_frame_with_geometry",
            side_effect=_fake_decode_frame_with_geometry,
        ):
            worker = DecodeWorker(
                worker_id=0,
                frame_queue=fq,
                release_queue=release_q,
                result_queue=rq,
                stop_event=stop,
                stats=stats,
                protocol="layered",
            )
            worker.start()
            worker.join(timeout=2.0)

        snap = stats.snapshot()
        assert calls["decode_frame"] == 2
        assert calls["decode_frame_with_geometry"] == 5
        assert snap["geometry_reuse_fail_count"] == 5
        assert snap["lock_locked_to_acquire"] == 1
