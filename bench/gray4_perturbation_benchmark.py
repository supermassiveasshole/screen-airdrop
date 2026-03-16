#!/usr/bin/env python3
"""Replay gray4 frames under controlled perturbations to isolate payload fragility."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np

try:
    from analyze_debug_snapshots import analyze_debug_dir
    from benchmark_common import write_json_result
except ModuleNotFoundError:
    try:
        from bench.analyze_debug_snapshots import analyze_debug_dir
        from bench.benchmark_common import write_json_result
    except ModuleNotFoundError:
        _THIS_DIR = Path(__file__).resolve().parent

        def _load_local_module(name: str, filename: str):
            spec = importlib.util.spec_from_file_location(name, _THIS_DIR / filename)
            if spec is None or spec.loader is None:
                raise ModuleNotFoundError(name)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module

        analyze_debug_dir = _load_local_module(
            "analyze_debug_snapshots", "analyze_debug_snapshots.py"
        ).analyze_debug_dir
        write_json_result = _load_local_module(
            "benchmark_common", "benchmark_common.py"
        ).write_json_result

from screen_airdrop.receiver.cli import main as receiver_main


def _identity(frame: np.ndarray) -> np.ndarray:
    return frame.copy()


def _gaussian_blur(frame: np.ndarray, ksize: int) -> np.ndarray:
    return cv2.GaussianBlur(frame, (ksize, ksize), 0)


def _gamma(frame: np.ndarray, gamma: float) -> np.ndarray:
    lut = np.array(
        [np.clip(((i / 255.0) ** gamma) * 255.0, 0.0, 255.0) for i in range(256)],
        dtype=np.uint8,
    )
    return cv2.LUT(frame, lut)


def _contrast(frame: np.ndarray, alpha: float) -> np.ndarray:
    return cv2.convertScaleAbs(frame, alpha=alpha, beta=0.0)


def _scaled(frame: np.ndarray, ratio: float, interpolation: int) -> np.ndarray:
    h, w = frame.shape[:2]
    down_w = max(64, int(round(w * ratio)))
    down_h = max(64, int(round(h * ratio)))
    small = cv2.resize(frame, (down_w, down_h), interpolation=interpolation)
    return cv2.resize(small, (w, h), interpolation=interpolation)


def _motion_blur(frame: np.ndarray, ksize: int) -> np.ndarray:
    kernel = np.zeros((ksize, ksize), dtype=np.float32)
    kernel[ksize // 2, :] = 1.0 / float(ksize)
    return cv2.filter2D(frame, -1, kernel)


def _case_specs() -> list[dict[str, Any]]:
    return [
        {"name": "clean", "apply": _identity},
        {"name": "gaussian_blur_3", "apply": lambda frame: _gaussian_blur(frame, 3)},
        {"name": "gaussian_blur_5", "apply": lambda frame: _gaussian_blur(frame, 5)},
        {"name": "scaled_area_0p97", "apply": lambda frame: _scaled(frame, 0.97, cv2.INTER_AREA)},
        {
            "name": "scaled_linear_0p94",
            "apply": lambda frame: _scaled(frame, 0.94, cv2.INTER_LINEAR),
        },
        {"name": "gamma_0p85", "apply": lambda frame: _gamma(frame, 0.85)},
        {"name": "gamma_1p15", "apply": lambda frame: _gamma(frame, 1.15)},
        {"name": "contrast_0p90", "apply": lambda frame: _contrast(frame, 0.90)},
        {"name": "motion_blur_5", "apply": lambda frame: _motion_blur(frame, 5)},
    ]


def _load_frames(frames_dir: Path) -> list[tuple[str, np.ndarray]]:
    frames: list[tuple[str, np.ndarray]] = []
    for path in sorted(frames_dir.glob("*.npy")):
        frames.append((path.name, np.load(path)))
    if not frames:
        raise RuntimeError("no .npy replay frames found in {0}".format(frames_dir))
    return frames


def _write_frames(frames_dir: Path, frames: list[tuple[str, np.ndarray]], transform) -> None:
    frames_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in frames:
        np.save(frames_dir / name, transform(frame))


def _run_case(
    *,
    case_name: str,
    case_transform,
    frames: list[tuple[str, np.ndarray]],
    protocol: str,
    module_grid: str,
    max_idle_seconds: int,
    max_seconds: int,
    keep_artifacts: bool,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="gray4-perturb-") as tmp_root:
        root = Path(tmp_root)
        replay_dir = root / "frames"
        debug_dir = root / "debug"
        output_dir = root / "out"
        report_path = root / "report.json"
        _write_frames(replay_dir, frames, case_transform)
        exit_code = receiver_main(
            [
                "--source",
                "replay",
                "--frames-dir",
                str(replay_dir),
                "--protocol",
                protocol,
                "--module-grid",
                module_grid,
                "--output-dir",
                str(output_dir),
                "--report-json",
                str(report_path),
                "--debug-dir",
                str(debug_dir),
                "--debug-max-frames",
                "1000",
                "--debug-interval",
                "0",
                "--max-idle-seconds",
                str(max_idle_seconds),
                "--max-seconds",
                str(max_seconds),
            ]
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        analysis = analyze_debug_dir(debug_dir)
        result = {
            "benchmark_kind": "gray4_perturbation",
            "case": case_name,
            "exit_code": int(exit_code),
            "status": str(report.get("status", "")),
            "grid_size": module_grid,
            "protocol": protocol,
            "total_frames": int(analysis.get("total_frames", 0)),
            "failed_frames": int(analysis.get("failed_frames", 0)),
            "failure_rate": float(analysis.get("failure_rate", 0.0)),
            "data_failure_rate": float(
                analysis.get("by_plane", {}).get("data", {}).get("failure_rate", 0.0)
            ),
            "control_failure_rate": float(
                analysis.get("by_plane", {}).get("control", {}).get("failure_rate", 0.0)
            ),
            "unknown_failure_rate": float(
                analysis.get("by_plane", {}).get("unknown", {}).get("failure_rate", 0.0)
            ),
            "decode_errors": dict(analysis.get("decode_errors", {})),
            "primary_decode_error": next(iter(analysis.get("decode_errors", {})), ""),
            "goodput_kibps": float(report.get("goodput_kibps", 0.0)),
            "bad_frame_rate": float(report.get("bad_frame_rate", 0.0)),
            "locator_fail_rate": float(report.get("locator_fail_rate", 0.0)),
            "mean_locator_confidence": float(report.get("mean_locator_confidence", 0.0)),
            "avg_decode_ms": float(report.get("avg_decode_ms", 0.0)),
        }
        if keep_artifacts:
            artifact_root = Path(tempfile.gettempdir()) / "gray4-perturb-artifacts" / case_name
            if artifact_root.exists():
                shutil.rmtree(artifact_root)
            artifact_root.mkdir(parents=True, exist_ok=True)
            shutil.copytree(debug_dir, artifact_root / "debug")
            shutil.copytree(replay_dir, artifact_root / "frames")
            shutil.copy(report_path, artifact_root / "report.json")
            result["artifact_dir"] = str(artifact_root)
        return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark gray4 replay fragility under perturbation.")
    parser.add_argument("--frames-dir", required=True, help="source .npy replay frame directory")
    parser.add_argument("--protocol", choices=["gray4"], default="gray4")
    parser.add_argument("--module-grid", default="224x136")
    parser.add_argument("--max-idle-seconds", type=int, default=15)
    parser.add_argument("--max-seconds", type=int, default=300)
    parser.add_argument("--cases", default="", help="comma-separated case names to run")
    parser.add_argument("--keep-artifacts", action="store_true", help="keep per-case debug artifacts")
    parser.add_argument("--output-json", default="", help="optional explicit output path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    frames = _load_frames(Path(args.frames_dir))
    all_cases = _case_specs()
    selected = {
        token.strip()
        for token in args.cases.split(",")
        if token.strip()
    }
    cases = [case for case in all_cases if not selected or case["name"] in selected]
    results = [
        _run_case(
            case_name=case["name"],
            case_transform=case["apply"],
            frames=frames,
            protocol=args.protocol,
            module_grid=args.module_grid,
            max_idle_seconds=int(args.max_idle_seconds),
            max_seconds=int(args.max_seconds),
            keep_artifacts=bool(args.keep_artifacts),
        )
        for case in cases
    ]
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Wrote", output_path)
    else:
        output_path = write_json_result("gray4_perturbation_benchmark", results)
        print("Wrote", output_path)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
