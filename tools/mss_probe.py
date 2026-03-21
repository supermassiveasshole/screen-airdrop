"""Minimal MSS probe for measuring wall/cpu capture jitter."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

import mss


def _parse_roi(value: str) -> tuple[int, int, int, int]:
    parts = [int(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        msg = "ROI must be x,y,w,h"
        raise argparse.ArgumentTypeError(msg)
    x, y, w, h = parts
    if w <= 0 or h <= 0:
        msg = "ROI width and height must be positive"
        raise argparse.ArgumentTypeError(msg)
    return x, y, w, h


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * pct))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roi", type=_parse_roi, required=True, help="x,y,w,h")
    parser.add_argument("--monitor-index", type=int, default=1)
    parser.add_argument("--fps", type=float, default=55.0)
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()

    x, y, w, h = args.roi
    target_interval = 1.0 / args.fps if args.fps > 0 else 0.0
    deadline = time.perf_counter()
    end_time = deadline + args.seconds

    wall_samples: list[float] = []
    cpu_samples: list[float] = []
    lag_samples: list[float] = []
    hashes: list[int] = []

    monitor: dict[str, Any] = {
        "left": x,
        "top": y,
        "width": w,
        "height": h,
        "mon": args.monitor_index,
    }

    with mss.mss() as sct:
        while True:
            now = time.perf_counter()
            if now >= end_time:
                break
            if now < deadline:
                time.sleep(min(0.001, deadline - now))
                continue

            lag_ms = max(0.0, (now - deadline) * 1000.0)
            t0 = time.perf_counter()
            cpu0 = time.thread_time()
            shot = sct.grab(monitor)
            cpu1 = time.thread_time()
            t1 = time.perf_counter()

            wall_ms = (t1 - t0) * 1000.0
            cpu_ms = (cpu1 - cpu0) * 1000.0
            wall_samples.append(wall_ms)
            cpu_samples.append(cpu_ms)
            lag_samples.append(lag_ms)
            hashes.append(hash(bytes(shot.raw[: min(4096, len(shot.raw))])))

            deadline += target_interval
            now_after = time.perf_counter()
            if now_after >= deadline:
                deadline = now_after

    distinct_hashes = len(set(hashes))
    result = {
        "roi": {"x": x, "y": y, "w": w, "h": h},
        "monitor_index": args.monitor_index,
        "fps": args.fps,
        "seconds": args.seconds,
        "samples": len(wall_samples),
        "distinct_hashes": distinct_hashes,
        "wall_ms": {
            "mean": round(statistics.fmean(wall_samples), 3) if wall_samples else 0.0,
            "p50": round(statistics.median(wall_samples), 3) if wall_samples else 0.0,
            "p95": round(_percentile(wall_samples, 0.95), 3),
            "max": round(max(wall_samples), 3) if wall_samples else 0.0,
        },
        "cpu_ms": {
            "mean": round(statistics.fmean(cpu_samples), 3) if cpu_samples else 0.0,
            "p50": round(statistics.median(cpu_samples), 3) if cpu_samples else 0.0,
            "p95": round(_percentile(cpu_samples, 0.95), 3),
            "max": round(max(cpu_samples), 3) if cpu_samples else 0.0,
        },
        "deadline_lag_ms": {
            "mean": round(statistics.fmean(lag_samples), 3) if lag_samples else 0.0,
            "p95": round(_percentile(lag_samples, 0.95), 3),
            "max": round(max(lag_samples), 3) if lag_samples else 0.0,
        },
    }

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_json:
        args.output_json.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
