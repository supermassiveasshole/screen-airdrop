"""Compact protocol wiring tests."""

from __future__ import annotations

from unittest.mock import patch

from screen_airdrop.receiver.cli import _should_use_pipeline
from screen_airdrop.receiver.cli import build_parser as build_receiver_parser
from screen_airdrop.receiver.pipeline import ReceiverPipeline
from screen_airdrop.sender.legacy import build_parser as build_legacy_sender_parser
from screen_airdrop.sender.modern import build_parser as build_modern_sender_parser


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


def test_compact_uses_pipeline_when_debug_disabled():
    assert _should_use_pipeline(
        source="screen",
        protocol="compact",
        debug_dir=None,
        needs_runtime_roi_selection=False,
    )
