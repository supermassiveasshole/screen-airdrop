#!/usr/bin/env python3
"""Shared helpers for benchmark scripts."""

from __future__ import annotations

import json
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from screen_airdrop.common.protocol_interface import LayoutInfo
from screen_airdrop.receiver.protocol_adapter_basic import BasicProtocolDecoder
from screen_airdrop.receiver.protocol_adapter_compact import CompactProtocolDecoder
from screen_airdrop.sender.protocol_adapter_basic import BasicProtocolEncoder
from screen_airdrop.sender.protocol_adapter_compact import CompactProtocolEncoder

ROOT = Path(__file__).resolve().parents[1]
RESULT_ROOT = ROOT / "bench" / "results"
SAMPLE_ROOT = ROOT / "bench" / "generated_samples"
ECC_LEVELS = ("L", "M", "Q", "H")
PAYLOAD_MODES = ("fixed", "max")
LAYOUT_MODES = ("same_grid", "footprint_matched")
DISPLAY_MODES = ("small", "medium", "large", "fullscreen")

DEFAULT_BASIC_GRID_W = 160
DEFAULT_BASIC_GRID_H = 96
DEFAULT_BASIC_QUIET = 4
DEFAULT_BASIC_FINDER = 9
DEFAULT_BASIC_GUARD = 2
DEFAULT_COMPACT_QUIET = 4
DEFAULT_COMPACT_FINDER = 7
DEFAULT_COMPACT_GUARD = 1

BASIC_FRAME_W = 2 * DEFAULT_BASIC_QUIET + 2 * DEFAULT_BASIC_FINDER + 2 * DEFAULT_BASIC_GUARD + DEFAULT_BASIC_GRID_W
BASIC_FRAME_H = 2 * DEFAULT_BASIC_QUIET + 2 * DEFAULT_BASIC_FINDER + 2 * DEFAULT_BASIC_GUARD + DEFAULT_BASIC_GRID_H

DISPLAY_DIMENSIONS: dict[str, tuple[int, int]] = {
    "small": (960, 540),
    "medium": (1280, 720),
    "large": (1600, 900),
    "fullscreen": (1920, 1080),
}

DISPLAY_NOTES: dict[str, str] = {
    "small": "Render the sender in a small centered window, about 960x540.",
    "medium": "Render the sender in a medium window, about 1280x720.",
    "large": "Render the sender in a large window, about 1600x900.",
    "fullscreen": "Render the sender fullscreen or as large as the display allows (about 1920x1080).",
}


@dataclass(frozen=True)
class ProtocolConfig:
    protocol: str
    grid_w: int = 160
    grid_h: int = 96


def _compact_grid_for_basic_footprint() -> tuple[int, int]:
    compact_overhead_w = 2 * DEFAULT_COMPACT_QUIET + 2 * DEFAULT_COMPACT_FINDER + 2 * DEFAULT_COMPACT_GUARD
    compact_overhead_h = 2 * DEFAULT_COMPACT_QUIET + 2 * DEFAULT_COMPACT_FINDER + 2 * DEFAULT_COMPACT_GUARD
    return (
        BASIC_FRAME_W - compact_overhead_w,
        BASIC_FRAME_H - compact_overhead_h,
    )


def protocol_configs(protocol: str, layout_mode: str = "same_grid") -> list[ProtocolConfig]:
    if layout_mode not in LAYOUT_MODES:
        raise ValueError(f"unsupported layout mode: {layout_mode}")
    compact_grid_w, compact_grid_h = _compact_grid_for_basic_footprint()
    if protocol == "all":
        if layout_mode == "footprint_matched":
            return [
                ProtocolConfig("basic", grid_w=DEFAULT_BASIC_GRID_W, grid_h=DEFAULT_BASIC_GRID_H),
                ProtocolConfig("compact", grid_w=compact_grid_w, grid_h=compact_grid_h),
            ]
        return [ProtocolConfig("basic"), ProtocolConfig("compact")]
    if protocol == "compact" and layout_mode == "footprint_matched":
        return [ProtocolConfig("compact", grid_w=compact_grid_w, grid_h=compact_grid_h)]
    return [ProtocolConfig(protocol)]


def make_encoder(config: ProtocolConfig, ecc_level: str):
    if config.protocol == "basic":
        return BasicProtocolEncoder(
            grid_w=config.grid_w,
            grid_h=config.grid_h,
            ecc_level=ecc_level,
        )
    if config.protocol == "compact":
        return CompactProtocolEncoder(
            grid_w=config.grid_w,
            grid_h=config.grid_h,
            ecc_level=ecc_level,
        )
    raise ValueError(f"unsupported protocol: {config.protocol}")


def make_decoder(config: ProtocolConfig):
    if config.protocol == "basic":
        return BasicProtocolDecoder(grid_w=config.grid_w, grid_h=config.grid_h)
    if config.protocol == "compact":
        return CompactProtocolDecoder(grid_w=config.grid_w, grid_h=config.grid_h)
    raise ValueError(f"unsupported protocol: {config.protocol}")


def layout_payload_capacity_bytes(layout: LayoutInfo) -> int:
    return max(0, int(layout.data_capacity_bits) // 8)


def protocol_safe_chunk_size(layout: LayoutInfo) -> int:
    cap = layout_payload_capacity_bytes(layout)
    return min(cap, max(64, int(cap * 0.9)))


def payload_size_for_mode(layout: LayoutInfo, payload_mode: str, requested_bytes: int) -> int:
    if payload_mode not in PAYLOAD_MODES:
        raise ValueError(f"invalid payload mode: {payload_mode}")
    if payload_mode == "max":
        return protocol_safe_chunk_size(layout)
    return min(max(1, int(requested_bytes)), protocol_safe_chunk_size(layout))


def payload_size_for_ratio(layout: LayoutInfo, payload_ratio: float) -> int:
    if payload_ratio <= 0.0 or payload_ratio > 1.0:
        raise ValueError(f"payload ratio must be within (0, 1], got {payload_ratio}")
    cap = layout_payload_capacity_bytes(layout)
    return min(cap, max(64, int(cap * payload_ratio)))


def payload_bits_per_module(layout: LayoutInfo, payload_bytes: int) -> float:
    total_modules = max(1, int(layout.frame_w) * int(layout.frame_h))
    return float(payload_bytes * 8) / float(total_modules)


def display_dimensions(display_mode: str) -> tuple[int, int]:
    if display_mode not in DISPLAY_DIMENSIONS:
        raise ValueError(f"unsupported display mode: {display_mode}")
    return DISPLAY_DIMENSIONS[display_mode]


def display_note(display_mode: str) -> str:
    if display_mode not in DISPLAY_NOTES:
        raise ValueError(f"unsupported display mode: {display_mode}")
    return DISPLAY_NOTES[display_mode]


def raw_pngs(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob("*.raw.png"))


def load_basic_real_frames(repo_root: Path) -> tuple[str, list[Path]]:
    spec_path = repo_root / "tests" / "fixtures" / "v31_regression_cases.json"
    if not spec_path.exists():
        return ("basic_regression", [])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    frames: list[Path] = []
    for case in spec.get("cases", []):
        frame_path = repo_root / str(case["frame_path"])
        if frame_path.exists() and frame_path.name.endswith(".raw.png"):
            frames.append(frame_path)
    return ("basic_regression", frames)


def load_compact_real_datasets(repo_root: Path) -> list[tuple[str, list[Path]]]:
    datasets: list[tuple[str, list[Path]]] = []
    for name in ("compact", "compact_v4"):
        frames = raw_pngs(repo_root / "debug" / name)
        if frames:
            datasets.append((name, frames))
    return datasets


def load_real_datasets(repo_root: Path, protocol: str) -> list[tuple[str, list[Path]]]:
    if protocol == "basic":
        return [load_basic_real_frames(repo_root)]
    if protocol == "compact":
        return load_compact_real_datasets(repo_root)
    if protocol == "all":
        datasets = [load_basic_real_frames(repo_root)]
        datasets.extend(load_compact_real_datasets(repo_root))
        return datasets
    raise ValueError(f"unsupported protocol: {protocol}")


def timestamp_slug() -> str:
    return str(int(time.time()))


def write_json_result(prefix: str, payload: Any) -> Path:
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = RESULT_ROOT / f"{prefix}_{timestamp_slug()}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def ensure_sample_payload_file(stem: str, size_bytes: int) -> Path:
    if size_bytes <= 0:
        raise ValueError("size_bytes must be > 0")
    SAMPLE_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = SAMPLE_ROOT / f"{stem}_{size_bytes}.bin"
    if out_path.exists() and out_path.stat().st_size == size_bytes:
        return out_path
    rng = random.Random(stem)
    remaining = size_bytes
    block_size = 1024 * 1024
    with out_path.open("wb") as handle:
        while remaining > 0:
            count = min(block_size, remaining)
            handle.write(bytes(rng.randrange(0, 256) for _ in range(count)))
            remaining -= count
    return out_path


def protocol_config_dict(config: ProtocolConfig) -> dict[str, Any]:
    return asdict(config)
