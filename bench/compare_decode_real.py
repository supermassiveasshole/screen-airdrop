#!/usr/bin/env python3
"""Benchmark real captured frames for locator + decode cost."""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

try:
    from benchmark_common import load_real_datasets, write_json_result
except ModuleNotFoundError:
    from bench.benchmark_common import load_real_datasets, write_json_result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Real-frame locator + decode benchmark.")
    parser.add_argument("--protocol", choices=["basic", "compact", "gray4", "all"], default="all")
    parser.add_argument("--iterations", type=int, default=15)
    parser.add_argument("--output-json", type=str, default="")
    return parser.parse_args()


def _basic_decoder(frame: np.ndarray) -> tuple[Any, bytes, Any]:
    from screen_airdrop.receiver.decoder_basic import decode_frame_basic

    return decode_frame_basic(
        frame=frame,
        detect_mode="full",
        grid_w=160,
        grid_h=96,
    )


def _compact_decoder(frame: np.ndarray) -> tuple[Any, bytes, Any]:
    from screen_airdrop.receiver.decoder_compact import decode_frame_compact

    return decode_frame_compact(
        frame=frame,
        detect_mode="track",
        forced_roi=(0, 0, frame.shape[1], frame.shape[0]),
        roi_only=True,
        manual_strict=True,
        grid_w=160,
        grid_h=96,
        guard_band=1,
        corner_size=7,
        locator_engine="auto",
    )


def benchmark_dataset(
    *,
    protocol: str,
    dataset_name: str,
    frame_paths: list[Path],
    decoder: Callable[[np.ndarray], tuple[Any, bytes, Any]],
    iterations: int,
) -> dict[str, Any]:
    decode_times = []
    locator_counts: Counter[str] = Counter()
    success_count = 0
    failures: list[str] = []

    for frame_path in frame_paths[:iterations]:
        frame = cv2.imread(str(frame_path))
        if frame is None:
            failures.append(f"{frame_path.name}: imread_failed")
            continue
        t0 = time.perf_counter()
        try:
            _header, _payload, meta = decoder(frame)
            t1 = time.perf_counter()
            decode_times.append((t1 - t0) * 1000.0)
            locator_counts[str(getattr(meta, "locator_engine", ""))] += 1
            success_count += 1
        except Exception as exc:
            t1 = time.perf_counter()
            decode_times.append((t1 - t0) * 1000.0)
            failures.append(f"{frame_path.name}: {exc}")

    return {
        "benchmark_kind": "real_frame_decode",
        "protocol": protocol,
        "dataset_name": dataset_name,
        "frames_total": len(frame_paths[:iterations]),
        "success_rate": 0.0 if not decode_times else float(success_count) / float(len(decode_times)),
        "locator_decode_ms_avg": 0.0 if not decode_times else float(np.mean(decode_times)),
        "locator_decode_ms_std": 0.0 if not decode_times else float(np.std(decode_times)),
        "locator_engine_breakdown": dict(locator_counts),
        "failures": failures,
    }


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]

    decoder_map: dict[str, Callable[[np.ndarray], tuple[Any, bytes, Any]]] = {
        "basic": _basic_decoder,
        "compact": _compact_decoder,
    }

    protocols = ["basic", "compact"] if args.protocol == "all" else [args.protocol]
    results: list[dict[str, Any]] = []

    for protocol in protocols:
        datasets = load_real_datasets(repo_root, protocol)
        for dataset_name, frame_paths in datasets:
            if not frame_paths:
                continue
            result = benchmark_dataset(
                protocol=protocol,
                dataset_name=dataset_name,
                frame_paths=frame_paths,
                decoder=decoder_map[protocol],
                iterations=args.iterations,
            )
            results.append(result)
            print(
                json.dumps(
                    {
                        "protocol": protocol,
                        "dataset": dataset_name,
                        "success_rate": round(result["success_rate"], 4),
                        "locator_decode_ms_avg": round(result["locator_decode_ms_avg"], 2),
                        "locator_engine_breakdown": result["locator_engine_breakdown"],
                    },
                    ensure_ascii=False,
                )
            )

    out_path = write_json_result("real_frame_decode_benchmark", results)
    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
    print("Saved:", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
