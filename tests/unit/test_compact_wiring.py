# pyright: reportArgumentType=false
"""Compact protocol wiring tests."""

from __future__ import annotations

from unittest.mock import patch

from screen_airdrop.receiver.cli import _should_use_pipeline
from screen_airdrop.receiver.cli import build_parser as build_receiver_parser
from screen_airdrop.receiver.pipeline import ReceiverPipeline
from screen_airdrop.receiver.roi_policy import RoiPolicy
from screen_airdrop.sender.legacy import build_parser as build_legacy_sender_parser
from screen_airdrop.sender.modern import build_parser as build_modern_sender_parser
from screen_airdrop.sender.schedule_policy import BroadcastSchedule


class _DummyCapture:
    monitor_index = 1
    window_title = None
    region = None
    active_region = None
    _mss_mod = None


def test_sender_parsers_accept_compact_protocol():
    modern_args = build_modern_sender_parser().parse_args(["input.bin", "--protocol", "compact"])
    legacy_args = build_legacy_sender_parser().parse_args(["input.bin", "--protocol", "compact"])

    assert modern_args.protocol == "compact"
    assert legacy_args.protocol == "compact"


def test_receiver_parser_accepts_compact_protocol():
    args = build_receiver_parser().parse_args(["--protocol", "compact"])
    assert args.protocol == "compact"


def test_receiver_pipeline_uses_compact_geometry_defaults():
    with patch("screen_airdrop.receiver.pipeline.CompactProtocolDecoder") as compact_decoder:
        pipeline = ReceiverPipeline(
            capture=_DummyCapture(),
            assembler=object(),
            protocol="compact",
            num_workers=1,
        )

    assert len(pipeline._decode_workers) == 1
    kwargs = compact_decoder.call_args.kwargs
    assert kwargs["guard_band"] == 1
    assert kwargs["corner_size"] == 7


def test_receiver_parser_accepts_gray4_protocol():
    args = build_receiver_parser().parse_args(["--protocol", "gray4"])
    assert args.protocol == "gray4"


def test_receiver_parser_accepts_layered_protocol():
    args = build_receiver_parser().parse_args(["--protocol", "layered"])
    assert args.protocol == "layered"


def test_receiver_parser_accepts_pipeline_queue_overrides():
    args = build_receiver_parser().parse_args(
        ["--frame-queue-size", "96", "--result-queue-size", "512"]
    )
    assert args.frame_queue_size == 96
    assert args.result_queue_size == 512


def test_receiver_parser_accepts_capture_dump_overrides():
    args = build_receiver_parser().parse_args(
        ["--capture-dump-dir", "/tmp/capdump", "--capture-dump-max-frames", "128"]
    )
    assert args.capture_dump_dir == "/tmp/capdump"
    assert args.capture_dump_max_frames == 128


def test_receiver_roi_interactive_is_canonicalized_to_manual_mode():
    args = build_receiver_parser().parse_args(["--roi-interactive"])
    policy = RoiPolicy.from_args(args)

    policy.apply_to_args(args)

    assert args.roi_interactive is True
    assert args.select_region is True
    assert args.roi_mode == "manual"
    assert policy.report_mode == "interactive"


def test_receiver_pipeline_uses_gray4_geometry_defaults():
    with patch("screen_airdrop.receiver.pipeline.Gray4ProtocolDecoder") as gray4_decoder:
        pipeline = ReceiverPipeline(
            capture=_DummyCapture(),
            assembler=object(),
            protocol="gray4",
            num_workers=1,
        )

    assert len(pipeline._decode_workers) == 1
    kwargs = gray4_decoder.call_args.kwargs
    assert kwargs["guard_band"] == 1
    assert kwargs["corner_size"] == 7


def test_receiver_pipeline_uses_layered_geometry_defaults():
    with patch("screen_airdrop.receiver.pipeline.LayeredProtocolDecoder") as layered_decoder:
        pipeline = ReceiverPipeline(
            capture=_DummyCapture(),
            assembler=object(),
            protocol="layered",
            num_workers=1,
        )

    assert len(pipeline._decode_workers) == 1
    kwargs = layered_decoder.call_args.kwargs
    assert kwargs["guard_band"] == 1
    assert kwargs["corner_size"] == 7


def test_receiver_pipeline_uses_explicit_queue_sizes():
    pipeline = ReceiverPipeline(
        capture=_DummyCapture(),
        assembler=object(),
        protocol="gray4",
        num_workers=1,
        frame_queue_size=96,
        result_queue_size=512,
    )

    assert pipeline._frame_queue.maxsize == 96
    assert pipeline._result_queue.maxsize == 512


def test_receiver_pipeline_accepts_capture_dump_config(tmp_path):
    dump_dir = tmp_path / "capture-dump"
    pipeline = ReceiverPipeline(
        capture=_DummyCapture(),
        assembler=object(),
        protocol="gray4",
        num_workers=1,
        capture_dump_dir=str(dump_dir),
        capture_dump_max_frames=12,
    )

    assert dump_dir.is_dir()
    assert pipeline._capture_thread._dump_dir == str(dump_dir)
    assert pipeline._capture_thread._dump_max_frames == 12


def test_compact_uses_pipeline_when_debug_disabled():
    assert _should_use_pipeline(
        source="screen",
        protocol="compact",
        debug_dir=None,
        needs_runtime_roi_selection=False,
    )


def test_gray4_uses_pipeline_when_debug_disabled():
    assert _should_use_pipeline(
        source="screen",
        protocol="gray4",
        debug_dir=None,
        needs_runtime_roi_selection=False,
    )


def test_layered_uses_pipeline_when_debug_disabled():
    assert _should_use_pipeline(
        source="screen",
        protocol="layered",
        debug_dir=None,
        needs_runtime_roi_selection=False,
    )


def test_modern_sender_gray4_defaults_to_higher_manifest_repeat():
    with patch("screen_airdrop.sender.modern.run_sender", return_value=0) as run_sender:
        from screen_airdrop.sender.modern import main as modern_main

        rc = modern_main(["input.bin", "--protocol", "gray4"])

    assert rc == 0
    kwargs = run_sender.call_args.kwargs
    assert kwargs["protocol"] == "gray4"
    assert kwargs["manifest_repeat"] == 8
    assert kwargs["schedule"] == BroadcastSchedule(sync_frames=8, control_burst_repeat=8)


def test_modern_sender_layered_uses_layered_startup_defaults():
    with patch("screen_airdrop.sender.modern.run_sender", return_value=0) as run_sender:
        from screen_airdrop.sender.modern import main as modern_main

        rc = modern_main(["input.bin", "--protocol", "layered"])

    assert rc == 0
    kwargs = run_sender.call_args.kwargs
    assert kwargs["protocol"] == "layered"
    assert kwargs["manifest_repeat"] == 4
    assert kwargs["schedule"] == BroadcastSchedule(sync_frames=4, control_burst_repeat=4)


def test_sender_parsers_accept_manifest_repeat_override():
    modern_args = build_modern_sender_parser().parse_args(
        ["input.bin", "--protocol", "gray4", "--manifest-repeat", "12"]
    )
    legacy_args = build_legacy_sender_parser().parse_args(["input.bin", "--manifest-repeat", "7"])

    assert modern_args.manifest_repeat == 12
    assert legacy_args.manifest_repeat == 7


def test_sender_parsers_accept_chunk_fill_ratio_override():
    modern_args = build_modern_sender_parser().parse_args(
        ["input.bin", "--protocol", "gray4", "--chunk-fill-ratio", "1.0"]
    )
    legacy_args = build_legacy_sender_parser().parse_args(
        ["input.bin", "--chunk-fill-ratio", "0.95"]
    )

    assert modern_args.chunk_fill_ratio == 1.0
    assert legacy_args.chunk_fill_ratio == 0.95
