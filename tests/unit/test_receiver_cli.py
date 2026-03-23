from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from screen_airdrop.receiver.runtime.screen_capture import ScreenCapture
from screen_airdrop.receiver.cli import _build_source, _select_capture_region, build_parser


def test_build_parser_defaults_decode_workers_to_one() -> None:
    args = build_parser().parse_args([])
    assert int(args.decode_workers) == 1


def test_build_source_preserves_capture_crop_when_manual() -> None:
    config = SimpleNamespace(
        is_replay_mode=lambda: False,
        window_title="demo",
        monitor_index=1,
    )

    source = _build_source(cast(Any, config), (1, 2, 300, 400))

    assert isinstance(source, ScreenCapture)
    assert source.region == (1, 2, 300, 400)


def test_build_source_uses_full_capture_when_region_missing() -> None:
    config = SimpleNamespace(
        is_replay_mode=lambda: False,
        window_title="demo",
        monitor_index=1,
    )

    source = _build_source(cast(Any, config), None)

    assert isinstance(source, ScreenCapture)
    assert source.region is None


def test_select_capture_region_keeps_hint_outside_manual_mode() -> None:
    roi_policy = SimpleNamespace(mode="auto")
    assert _select_capture_region(cast(Any, roi_policy), (1, 2, 300, 400)) == (1, 2, 300, 400)


def test_select_capture_region_uses_crop_in_manual_mode() -> None:
    roi_policy = SimpleNamespace(mode="manual")
    assert _select_capture_region(cast(Any, roi_policy), (1, 2, 300, 400)) == (1, 2, 300, 400)
