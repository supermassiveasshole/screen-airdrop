#!/usr/bin/env python3
"""Inspect gray4 sender/captured frames at the module-sampling level."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from screen_airdrop.common.protocol_basic import (
    ECC_TO_REP,
    HEADER_SIZE,
    FormatInfoBasic,
    FrameHeaderBasic,
)
from screen_airdrop.receiver.control_decode import (
    _logical_scores_for_map,
    decode_binary_control_header,
)
from screen_airdrop.receiver.decoder_gray4 import (
    _fit_gray4_centers,
    _header_threshold_candidates,
    _mask_bit,
    _read_format_bits_gray4,
    _sample_gray4_bbox,
)
from screen_airdrop.receiver.protocol_adapter_gray4 import Gray4ProtocolDecoder
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


def _data_confidences(layout, confidences: list[float]) -> list[float]:
    values: list[float] = []
    for x, y in layout.data_coords:
        idx = y * layout.frame_w + x
        if idx < len(confidences):
            values.append(float(confidences[idx]))
    return values


def _masked_payload_symbols(modules: np.ndarray, layout, mask_id: int) -> np.ndarray:
    symbols: list[int] = []
    for x, y in layout.data_coords:
        sym = int(modules[y, x]) & 0x03
        if _mask_bit(mask_id, x, y):
            sym ^= 0x03
        symbols.append(sym)
    return np.asarray(symbols, dtype=np.uint8)


def _transition_density(modules: np.ndarray) -> dict[str, float]:
    if modules.size == 0:
        return {"horizontal": 0.0, "vertical": 0.0, "combined": 0.0}
    horiz = float(np.mean(modules[:, 1:] != modules[:, :-1])) if modules.shape[1] > 1 else 0.0
    vert = float(np.mean(modules[1:, :] != modules[:-1, :])) if modules.shape[0] > 1 else 0.0
    return {
        "horizontal": round(horiz, 6),
        "vertical": round(vert, 6),
        "combined": round((horiz + vert) / 2.0, 6),
    }


def _binary_transition_density(binary_modules: np.ndarray) -> dict[str, float]:
    return _transition_density(binary_modules.astype(np.uint8))


def _top_transition_lines(modules: np.ndarray, axis: int, top_n: int = 5) -> list[dict[str, float]]:
    scores: list[tuple[int, float]] = []
    if axis == 0 and modules.shape[0] > 0:
        for idx in range(modules.shape[0]):
            row = modules[idx, :]
            score = float(np.mean(row[1:] != row[:-1])) if row.size > 1 else 0.0
            scores.append((idx, score))
    elif axis == 1 and modules.shape[1] > 0:
        for idx in range(modules.shape[1]):
            col = modules[:, idx]
            score = float(np.mean(col[1:] != col[:-1])) if col.size > 1 else 0.0
            scores.append((idx, score))
    scores.sort(key=lambda item: item[1], reverse=True)
    return [
        {"index": int(idx), "transition_density": round(score, 6)}
        for idx, score in scores[:top_n]
    ]


def _symbol_hist(symbols: np.ndarray) -> dict[str, int]:
    return {str(idx): int(np.count_nonzero(symbols == idx)) for idx in range(4)}


def _symbol_balance(symbols: np.ndarray) -> dict[str, float]:
    if symbols.size == 0:
        return {"mean": 0.0, "std": 0.0}
    values = symbols.astype(np.float32)
    return {
        "mean": round(float(np.mean(values)), 6),
        "std": round(float(np.std(values)), 6),
    }


def _header_bit_analysis(
    *,
    avg_gray_u8: np.ndarray,
    header_modules: np.ndarray,
    sample_stack_u8: np.ndarray,
    thresholds: list[int],
    layout,
    mask_id: int,
    repetition: int,
) -> dict[str, Any]:
    header_cell_count = HEADER_SIZE * 8 * repetition
    threshold_results: list[dict[str, Any]] = []
    best_scores: np.ndarray | None = None
    best_threshold: int | None = None
    best_strength = -1.0

    for threshold in thresholds:
        scores = _logical_scores_for_map(
            candidate_map=header_modules,
            sample_stack_u8=sample_stack_u8,
            threshold=int(threshold),
            data_coords=layout.data_coords,
            header_cell_count=header_cell_count,
            repetition=repetition,
            mask_id=mask_id,
            mask_bit_fn=_mask_bit,
        )
        arr = np.asarray(scores, dtype=np.float32)
        mean_abs = float(np.mean(np.abs(arr))) if arr.size else 0.0
        weakest = np.argsort(np.abs(arr))[:10]
        threshold_results.append(
            {
                "threshold": int(threshold),
                "mean_abs_score": round(mean_abs, 6),
                "weakest_bits": [
                    {
                        "bit_index": int(idx),
                        "score": round(float(arr[idx]), 6),
                        "abs_score": round(float(abs(arr[idx])), 6),
                    }
                    for idx in weakest
                ],
            }
        )
        if mean_abs > best_strength:
            best_strength = mean_abs
            best_scores = arr
            best_threshold = int(threshold)

    if best_scores is None:
        return {
            "mask_id": int(mask_id),
            "repetition": int(repetition),
            "selected_threshold": -1,
            "mean_abs_score": 0.0,
            "weakest_bits": [],
            "thresholds": [],
        }

    weakest = np.argsort(np.abs(best_scores))[:16]
    return {
        "mask_id": int(mask_id),
        "repetition": int(repetition),
        "selected_threshold": int(best_threshold),
        "mean_abs_score": round(float(np.mean(np.abs(best_scores))), 6),
        "weakest_bits": [
            {
                "bit_index": int(idx),
                "score": round(float(best_scores[idx]), 6),
                "abs_score": round(float(abs(best_scores[idx])), 6),
            }
            for idx in weakest
        ],
        "thresholds": threshold_results,
    }


def _payload_symbol_analysis(
    *,
    avg_gray_u8: np.ndarray,
    adaptive_modules: np.ndarray,
    confidences: list[float],
    layout,
) -> dict[str, Any]:
    symbol_rows: list[dict[str, Any]] = []
    for x, y in layout.data_coords:
        idx = y * layout.frame_w + x
        if idx >= len(confidences):
            continue
        symbol_rows.append(
            {
                "x": int(x),
                "y": int(y),
                "symbol": int(adaptive_modules[y, x]),
                "avg_gray": int(avg_gray_u8[y, x]),
                "confidence": float(confidences[idx]),
            }
        )
    symbol_rows.sort(key=lambda item: item["confidence"])
    weakest = symbol_rows[:16]
    return {
        "mean_confidence": round(
            float(np.mean([item["confidence"] for item in symbol_rows])) if symbol_rows else 0.0,
            6,
        ),
        "weakest_symbols": [
            {
                "x": int(item["x"]),
                "y": int(item["y"]),
                "symbol": int(item["symbol"]),
                "avg_gray": int(item["avg_gray"]),
                "confidence": round(float(item["confidence"]), 6),
            }
            for item in weakest
        ],
    }


def analyze_frame(
    path: Path,
    grid_w: int,
    grid_h: int,
    assume_mask_id: int | None = None,
) -> dict[str, Any]:
    frame = _load_frame(path)
    layout = build_layout_gray4(grid_w=grid_w, grid_h=grid_h)
    bbox = _expected_bbox(frame, layout.frame_w, layout.frame_h)
    sample_stack_u8, avg_gray_u8, header_modules, fixed_modules, adaptive_modules, static_modules, confidences = _sample_gray4_bbox(
        frame,
        bbox,
        layout,
    )
    centers = _fit_gray4_centers(avg_gray_u8, layout)
    thresholds = _header_threshold_candidates(avg_gray_u8, layout)
    decoder = Gray4ProtocolDecoder(grid_w=grid_w, grid_h=grid_h)
    result: dict[str, Any] = {
        "file": path.name,
        "bbox": {"x": bbox[0], "y": bbox[1], "w": bbox[2], "h": bbox[3]},
        "centers": [round(float(v), 3) for v in centers.tolist()],
        "header_threshold_candidates": [int(v) for v in thresholds],
        "frame_mean": round(float(np.mean(frame)), 3),
        "frame_std": round(float(np.std(frame)), 3),
        "avg_gray_mean": round(float(np.mean(avg_gray_u8)), 3),
        "avg_gray_std": round(float(np.std(avg_gray_u8)), 3),
        "fixed_symbol_hist": {
            str(idx): int(np.count_nonzero(fixed_modules == idx)) for idx in range(4)
        },
        "adaptive_symbol_hist": {
            str(idx): int(np.count_nonzero(adaptive_modules == idx)) for idx in range(4)
        },
    }
    data_conf = _data_confidences(layout, confidences)
    result["data_confidence"] = {
        "mean": round(float(np.mean(data_conf)) if data_conf else 0.0, 6),
        "lt_0_20": int(sum(1 for value in data_conf if value < 0.20)),
        "lt_0_40": int(sum(1 for value in data_conf if value < 0.40)),
    }

    pattern_mask_id: int | None = assume_mask_id
    try:
        fmt = FormatInfoBasic.unpack(_read_format_bits_gray4(static_modules, layout, binary=True))
        result["format"] = {
            "ok": True,
            "mask_id": int(fmt.mask_id),
            "ecc_id": int(fmt.ecc_id),
            "frame_type": int(fmt.frame_type),
        }
        pattern_mask_id = int(fmt.mask_id)
    except Exception as exc:  # noqa: BLE001
        result["format"] = {"ok": False, "error": str(exc)}

    try:
        header = decode_binary_control_header(
            avg_gray_u8=avg_gray_u8,
            header_maps=[header_modules],
            sample_stack_u8=sample_stack_u8,
            thresholds=thresholds,
            data_coords=layout.data_coords,
            header_size_bytes=HEADER_SIZE,
            repetition=ECC_TO_REP["L"],
            mask_id=3,
            mask_bit_fn=_mask_bit,
            unpack_header=FrameHeaderBasic.unpack,
        )
        result["header_mask3_rep1"] = {
            "ok": True,
            "chunk_id": int(header.chunk_id),
            "frame_id": int(header.frame_id),
            "payload_len": int(header.payload_len),
        }
    except Exception as exc:  # noqa: BLE001
        result["header_mask3_rep1"] = {"ok": False, "error": str(exc)}

    result["header_analysis"] = _header_bit_analysis(
        avg_gray_u8=avg_gray_u8,
        header_modules=header_modules,
        sample_stack_u8=sample_stack_u8,
        thresholds=thresholds,
        layout=layout,
        mask_id=3 if assume_mask_id is None else int(assume_mask_id),
        repetition=ECC_TO_REP["L"],
    )
    result["payload_symbol_analysis"] = _payload_symbol_analysis(
        avg_gray_u8=avg_gray_u8,
        adaptive_modules=adaptive_modules,
        confidences=confidences,
        layout=layout,
    )

    try:
        decoded = decoder.decode_frame(frame, detect_mode="full")
        result["decode"] = {
            "ok": True,
            "chunk_id": int(decoded.frame_header.chunk_id),
            "frame_id": int(decoded.frame_header.frame_id),
            "payload_len": int(len(decoded.payload)),
            "mask_id": int(getattr(decoded.meta, "mask_id", -1)),
        }
        if pattern_mask_id is None:
            pattern_mask_id = int(getattr(decoded.meta, "mask_id", -1))
    except Exception as exc:  # noqa: BLE001
        result["decode"] = {"ok": False, "error": str(exc)}

    if pattern_mask_id is not None and pattern_mask_id >= 0:
        payload_symbols = _masked_payload_symbols(adaptive_modules, layout, int(pattern_mask_id))
        binary_payload = (payload_symbols >= 2).astype(np.uint8)
        payload_grid = payload_symbols.reshape(layout.grid_h, layout.grid_w)
        binary_grid = binary_payload.reshape(layout.grid_h, layout.grid_w)
        result["payload_pattern"] = {
            "mask_id": int(pattern_mask_id),
            "masked_symbol_hist": _symbol_hist(payload_symbols),
            "masked_symbol_balance": _symbol_balance(payload_symbols),
            "symbol_transition_density": _transition_density(payload_grid),
            "binary_transition_density": _binary_transition_density(binary_grid),
            "top_transition_rows": _top_transition_lines(payload_grid, axis=0),
            "top_transition_cols": _top_transition_lines(payload_grid, axis=1),
        }
    else:
        result["payload_pattern"] = {
            "mask_id": -1,
            "masked_symbol_hist": {},
            "masked_symbol_balance": {"mean": 0.0, "std": 0.0},
            "symbol_transition_density": {"horizontal": 0.0, "vertical": 0.0, "combined": 0.0},
            "binary_transition_density": {"horizontal": 0.0, "vertical": 0.0, "combined": 0.0},
            "top_transition_rows": [],
            "top_transition_cols": [],
        }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze gray4 triplet frames")
    parser.add_argument("--module-grid", required=True, help="grid like 240x144")
    parser.add_argument("--frames", nargs="+", required=True, help="frame paths to inspect")
    parser.add_argument("--assume-mask-id", type=int, default=None, help="force mask id for payload-pattern analysis")
    parser.add_argument("--output-json", default=None, help="optional output json path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    grid_w, grid_h = [int(part) for part in str(args.module_grid).lower().split("x", 1)]
    results = [
        analyze_frame(Path(item), grid_w, grid_h, assume_mask_id=args.assume_mask_id)
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
