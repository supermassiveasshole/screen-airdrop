#!/usr/bin/env python3
"""Evaluate single-frame gray4 header ECC / recovery candidates on saved frames."""

from __future__ import annotations

import argparse
import itertools
import json
import time
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

from screen_airdrop.common.protocol_basic import HEADER_SIZE, FrameHeaderBasic
from screen_airdrop.receiver.control_decode import (
    _logical_scores_for_map,
    _try_unpack_candidates,
    decode_binary_control_header,
)
from screen_airdrop.receiver.decoder_gray4 import (
    _header_threshold_candidates,
    _mask_bit,
    _sample_gray4_bbox,
)
from screen_airdrop.sender.encoder_gray4 import build_layout_gray4


def _load_frame(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".npy":
        return np.load(path)
    import cv2  # pylint: disable=import-outside-toplevel

    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError("failed to read frame: {0}".format(path))
    return frame


def _expected_bbox(frame: np.ndarray, frame_w_modules: int, frame_h_modules: int) -> tuple[int, int, int, int]:
    height, width = frame.shape[:2]
    scale = max(1, min(width // frame_w_modules, height // frame_h_modules))
    symbol_w = frame_w_modules * scale
    symbol_h = frame_h_modules * scale
    ox = (width - symbol_w) // 2
    oy = (height - symbol_h) // 2
    return ox, oy, symbol_w, symbol_h


def _aggregate_threshold_scores(
    *,
    sample_stack_u8: np.ndarray,
    thresholds: Sequence[int],
    data_coords,
    header_cell_count: int,
    repetition: int,
    mask_id: int,
) -> list[float]:
    aggregate: np.ndarray | None = None
    for threshold in thresholds:
        scores = _logical_scores_for_map(
            candidate_map=np.zeros((1, 1), dtype=np.uint8),
            sample_stack_u8=sample_stack_u8,
            threshold=int(threshold),
            data_coords=data_coords,
            header_cell_count=header_cell_count,
            repetition=repetition,
            mask_id=mask_id,
            mask_bit_fn=_mask_bit,
        )
        arr = np.asarray(scores, dtype=np.float32)
        scale = max(1.0, float(np.mean(np.abs(arr))) if arr.size else 1.0)
        arr = arr / scale
        aggregate = arr if aggregate is None else (aggregate + arr)
    if aggregate is None:
        return []
    return [float(v) for v in aggregate.tolist()]


def _try_unpack_with_erasures(
    *,
    base_scores: Sequence[float],
    header_size_bytes: int,
    unpack_header: Callable[[bytes], Any],
    erasure_bits: int = 6,
) -> Any:
    last_exc: Exception | None = None
    abs_order = sorted(range(len(base_scores)), key=lambda idx: abs(float(base_scores[idx])))
    selected = abs_order[: min(erasure_bits, len(abs_order))]
    strong_bits = [1 if float(score) >= 0.0 else 0 for score in base_scores]

    # First try the current bit decisions.
    try:
        return unpack_header(_bits_to_bytes(strong_bits)[:header_size_bytes])
    except Exception as exc:  # noqa: BLE001
        last_exc = exc

    for assignment in itertools.product((0, 1), repeat=len(selected)):
        candidate_bits = list(strong_bits)
        for idx, bit in zip(selected, assignment):
            candidate_bits[idx] = int(bit)
        try:
            return unpack_header(_bits_to_bytes(candidate_bits)[:header_size_bytes])
        except Exception as exc:  # noqa: BLE001
            last_exc = exc

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("erasure candidate decode failed")


def _bits_to_bytes(bits: Sequence[int]) -> bytes:
    out = bytearray()
    for i in range(0, len(bits), 8):
        v = 0
        for bit in bits[i : i + 8]:
            v = (v << 1) | (int(bit) & 1)
        out.append(v)
    return bytes(out)


def _evaluate_baseline(
    *,
    avg_gray_u8: np.ndarray,
    header_modules: np.ndarray,
    sample_stack_u8: np.ndarray,
    thresholds: list[int],
    data_coords,
    repetition: int,
    mask_id: int,
) -> FrameHeaderBasic:
    return decode_binary_control_header(
        avg_gray_u8=avg_gray_u8,
        header_maps=[header_modules],
        sample_stack_u8=sample_stack_u8,
        thresholds=thresholds,
        data_coords=data_coords,
        header_size_bytes=HEADER_SIZE,
        repetition=repetition,
        mask_id=mask_id,
        mask_bit_fn=_mask_bit,
        unpack_header=FrameHeaderBasic.unpack,
    )


def _evaluate_aggregate_flips(
    *,
    sample_stack_u8: np.ndarray,
    thresholds: list[int],
    data_coords,
    repetition: int,
    mask_id: int,
) -> FrameHeaderBasic:
    header_cell_count = HEADER_SIZE * 8 * repetition
    aggregate_scores = _aggregate_threshold_scores(
        sample_stack_u8=sample_stack_u8,
        thresholds=thresholds,
        data_coords=data_coords,
        header_cell_count=header_cell_count,
        repetition=repetition,
        mask_id=mask_id,
    )
    return _try_unpack_candidates(
        base_scores=aggregate_scores,
        header_size_bytes=HEADER_SIZE,
        unpack_header=FrameHeaderBasic.unpack,
        max_uncertain=12,
        max_flips=3,
    )


def _evaluate_erasure(
    *,
    sample_stack_u8: np.ndarray,
    thresholds: list[int],
    data_coords,
    repetition: int,
    mask_id: int,
) -> FrameHeaderBasic:
    header_cell_count = HEADER_SIZE * 8 * repetition
    aggregate_scores = _aggregate_threshold_scores(
        sample_stack_u8=sample_stack_u8,
        thresholds=thresholds,
        data_coords=data_coords,
        header_cell_count=header_cell_count,
        repetition=repetition,
        mask_id=mask_id,
    )
    return _try_unpack_with_erasures(
        base_scores=aggregate_scores,
        header_size_bytes=HEADER_SIZE,
        unpack_header=FrameHeaderBasic.unpack,
        erasure_bits=6,
    )


def evaluate_frame(path: Path, grid_w: int, grid_h: int, mask_id: int, repetition: int) -> dict[str, Any]:
    frame = _load_frame(path)
    layout = build_layout_gray4(grid_w=grid_w, grid_h=grid_h)
    bbox = _expected_bbox(frame, layout.frame_w, layout.frame_h)
    sample_stack_u8, avg_gray_u8, header_modules, _fixed, _adaptive, _static, _confidences = _sample_gray4_bbox(
        frame,
        bbox,
        layout,
    )
    thresholds = _header_threshold_candidates(avg_gray_u8, layout)

    candidates = {
        "baseline": lambda: _evaluate_baseline(
            avg_gray_u8=avg_gray_u8,
            header_modules=header_modules,
            sample_stack_u8=sample_stack_u8,
            thresholds=thresholds,
            data_coords=layout.data_coords,
            repetition=repetition,
            mask_id=mask_id,
        ),
        "aggregate_flips": lambda: _evaluate_aggregate_flips(
            sample_stack_u8=sample_stack_u8,
            thresholds=thresholds,
            data_coords=layout.data_coords,
            repetition=repetition,
            mask_id=mask_id,
        ),
        "erasure_aware": lambda: _evaluate_erasure(
            sample_stack_u8=sample_stack_u8,
            thresholds=thresholds,
            data_coords=layout.data_coords,
            repetition=repetition,
            mask_id=mask_id,
        ),
    }

    record: dict[str, Any] = {
        "file": path.name,
        "mask_id": int(mask_id),
        "repetition": int(repetition),
        "thresholds": [int(v) for v in thresholds],
        "candidates": {},
    }
    for name, fn in candidates.items():
        started = time.perf_counter()
        try:
            header = fn()
            record["candidates"][name] = {
                "ok": True,
                "chunk_id": int(header.chunk_id),
                "frame_id": int(header.frame_id),
                "payload_len": int(header.payload_len),
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            }
        except Exception as exc:  # noqa: BLE001
            record["candidates"][name] = {
                "ok": False,
                "error": str(exc),
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            }
    return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate gray4 header ECC candidates")
    parser.add_argument("--module-grid", required=True, help="grid like 240x144")
    parser.add_argument("--frames", nargs="+", required=True, help="frames to evaluate")
    parser.add_argument("--mask-id", type=int, default=3, help="assumed mask id")
    parser.add_argument("--repetition", type=int, default=1, help="header repetition to test")
    parser.add_argument("--output-json", default=None, help="optional output json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    grid_w, grid_h = [int(part) for part in str(args.module_grid).lower().split("x", 1)]
    results = [
        evaluate_frame(Path(item), grid_w, grid_h, int(args.mask_id), int(args.repetition))
        for item in args.frames
    ]
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
