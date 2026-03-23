from pathlib import Path

from bench.benchmark_common import (
    display_dimensions,
    load_basic_real_frames,
    load_compact_real_datasets,
    payload_bits_per_module,
    payload_size_for_mode,
    payload_size_for_ratio,
    protocol_configs,
    protocol_safe_chunk_size,
)

from screen_airdrop.common.transport.protocol_interface import LayoutInfo


def _layout(capacity_bytes: int) -> LayoutInfo:
    return LayoutInfo(
        frame_w=100,
        frame_h=50,
        data_capacity_bits=capacity_bytes * 8,
        header_capacity_bits=0,
        protocol_name="test",
        protocol_version="1.0",
        bits_per_module=1,
    )


def test_payload_size_for_mode_fixed_is_clamped_to_protocol_safe_size():
    layout = _layout(1000)
    assert payload_size_for_mode(layout, "fixed", 5000) == protocol_safe_chunk_size(layout)
    assert payload_size_for_mode(layout, "fixed", 300) == 300


def test_payload_size_for_mode_max_uses_protocol_safe_size():
    layout = _layout(1000)
    assert payload_size_for_mode(layout, "max", 1) == protocol_safe_chunk_size(layout)


def test_payload_bits_per_module_uses_total_frame_modules():
    layout = _layout(1000)
    assert payload_bits_per_module(layout, 250) == 0.4


def test_payload_size_for_ratio_uses_capacity_ratio():
    layout = _layout(1000)
    assert payload_size_for_ratio(layout, 0.85) == 850


def test_display_dimensions_fullscreen():
    assert display_dimensions("fullscreen") == (1920, 1080)


def test_load_basic_real_frames_only_returns_raw_pngs():
    repo_root = Path(__file__).resolve().parents[2]
    dataset_name, frames = load_basic_real_frames(repo_root)
    assert dataset_name == "basic_regression"
    assert frames
    assert all(path.name.endswith(".raw.png") for path in frames)


def test_load_compact_real_datasets_only_return_raw_pngs():
    repo_root = Path(__file__).resolve().parents[2]
    datasets = load_compact_real_datasets(repo_root)
    assert datasets
    for _name, frames in datasets:
        assert frames
        assert all(path.name.endswith(".raw.png") for path in frames)


def test_protocol_configs_footprint_matched_expands_compact_grid():
    configs = protocol_configs("all", "footprint_matched")
    basic = next(cfg for cfg in configs if cfg.protocol == "basic")
    compact = next(cfg for cfg in configs if cfg.protocol == "compact")
    assert (basic.grid_w, basic.grid_h) == (160, 96)
    assert (compact.grid_w, compact.grid_h) == (166, 102)
