#!/usr/bin/env python3
"""Run replay/screen benchmark matrix and emit JSON results."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

import numpy as np

from screen_airdrop.receiver.cli import main as receiver_main
from screen_airdrop.sender.controller import build_encoded_frames
from screen_airdrop.sender.encoder import frame_capacity_bytes

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "real_data"
RESULT_ROOT = ROOT / "bench" / "results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["replay", "screen"], default="replay")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--protocol", choices=["v3_1", "v3"], default="v3_1")
    return parser.parse_args()


def list_datasets() -> list[Path]:
    names = ["docs_small", "bin_small", "mixed_tree", "code_large"]
    paths = [FIXTURE_ROOT / n for n in names]
    return [p for p in paths if p.exists()]


def _case_name(dataset: Path, block_size: int, fps: int, chunk_size: int, run_idx: int, protocol: str) -> str:
    return "{0}_{1}_b{2}_f{3}_c{4}_r{5}".format(dataset.name, protocol, block_size, fps, chunk_size, run_idx)


def run_case_replay(dataset: Path, block_size: int, fps: int, chunk_size: int, run_idx: int, protocol: str) -> dict:
    cap = frame_capacity_bytes(1920, 1080, block_size) if protocol != "v3_1" else 999999
    if chunk_size > cap:
        return {
            "case_name": _case_name(dataset, block_size, fps, chunk_size, run_idx, protocol),
            "mode": "replay",
            "protocol": protocol,
            "dataset": dataset.name,
            "block_size": block_size,
            "fps": fps,
            "chunk_size": chunk_size,
            "status": "skipped_unsupported_chunk",
            "frame_payload_cap": cap,
            "exit_code": -3,
        }

    with tempfile.TemporaryDirectory(prefix="sa-bench-") as td:
        tmp = Path(td)
        frame_dir = tmp / "frames"
        frame_dir.mkdir(parents=True, exist_ok=True)
        output_dir = tmp / "out"
        report_path = tmp / "receiver_report.json"

        encoded = build_encoded_frames(
            input_path=str(dataset),
            block_size=block_size,
            chunk_size=chunk_size,
            compress="gzip",
            sync_frames=20,
            epochs=2,
            protocol=protocol,
        )

        for i, item in enumerate(encoded["frames"]):
            np.save(frame_dir / "{0:06d}.npy".format(i), item["image"])

        started = time.time()
        code = receiver_main(
            [
                "--source",
                "replay",
                "--frames-dir",
                str(frame_dir),
                "--output-dir",
                str(output_dir),
                "--protocol",
                protocol,
                "--block-size",
                str(block_size),
                "--stats-interval",
                "0.2",
                "--max-seconds",
                "120",
                "--report-json",
                str(report_path),
            ]
        )
        elapsed = max(1e-6, time.time() - started)

        report = {}
        if report_path.exists():
            report = json.loads(report_path.read_text(encoding="utf-8"))

        report.update(
            {
                "case_name": _case_name(dataset, block_size, fps, chunk_size, run_idx, protocol),
                "mode": "replay",
                "protocol": protocol,
                "dataset": dataset.name,
                "block_size": block_size,
                "fps": fps,
                "chunk_size": chunk_size,
                "exit_code": code,
                "benchmark_elapsed_s": elapsed,
                "status": report.get("status", "missing_report"),
            }
        )
        return report


def run_case_screen(dataset: Path, block_size: int, fps: int, chunk_size: int, run_idx: int, protocol: str) -> dict:
    # Placeholder result object. Real interactive screen benchmark is manual.
    return {
        "case_name": _case_name(dataset, block_size, fps, chunk_size, run_idx, protocol),
        "mode": "screen",
        "protocol": protocol,
        "dataset": dataset.name,
        "block_size": block_size,
        "fps": fps,
        "chunk_size": chunk_size,
        "status": "skipped_manual_required",
        "exit_code": -1,
    }


def summarize(results: list[dict]) -> dict:
    ok = [r for r in results if r.get("status") == "ok"]
    goodputs = [float(r.get("goodput_kbps", 0.0)) for r in ok]
    e2e = [float(r.get("end_to_end_kbps", 0.0)) for r in ok]
    bad_rates = [float(r.get("bad_frame_rate", 0.0)) for r in ok]

    def p95(values: list[float]) -> float:
        if not values:
            return 0.0
        values = sorted(values)
        idx = int(round(0.95 * (len(values) - 1)))
        return values[idx]

    return {
        "total_cases": len(results),
        "ok_cases": len(ok),
        "avg_goodput_kbps": statistics.mean(goodputs) if goodputs else 0.0,
        "p95_end_to_end_kbps": p95(e2e),
        "avg_bad_frame_rate": statistics.mean(bad_rates) if bad_rates else 0.0,
    }


def main() -> int:
    args = parse_args()
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)

    datasets = list_datasets()
    if not datasets:
        print("No datasets found under tests/fixtures/real_data")
        return 1

    if args.quick:
        block_sizes = [6]
        fps_values = [12]
        chunk_sizes = [2048]
    else:
        block_sizes = [4, 6, 8]
        fps_values = [8, 12, 16]
        chunk_sizes = [8192, 16384, 32768]

    results = []
    for dataset in datasets:
        for block_size in block_sizes:
            for fps in fps_values:
                for chunk_size in chunk_sizes:
                    for run_idx in range(args.repeats):
                        try:
                            if args.mode == "replay":
                                report = run_case_replay(dataset, block_size, fps, chunk_size, run_idx, args.protocol)
                            else:
                                report = run_case_screen(dataset, block_size, fps, chunk_size, run_idx, args.protocol)
                        except Exception as exc:
                            report = {
                                "case_name": _case_name(dataset, block_size, fps, chunk_size, run_idx, args.protocol),
                                "mode": args.mode,
                                "protocol": args.protocol,
                                "dataset": dataset.name,
                                "block_size": block_size,
                                "fps": fps,
                                "chunk_size": chunk_size,
                                "status": "failed_exception",
                                "error": str(exc),
                                "exit_code": -2,
                            }
                        results.append(report)

    ts = int(time.time())
    out_path = RESULT_ROOT / "benchmark_{0}_{1}.json".format(args.mode, ts)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = summarize(results)
    summary_path = RESULT_ROOT / "summary_{0}_{1}.json".format(args.mode, ts)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Saved:", out_path)
    print("Saved:", summary_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
