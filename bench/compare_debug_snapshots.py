#!/usr/bin/env python3
"""Batch-compare receiver debug snapshot directories."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

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


def _parse_labels(spec: str, count: int) -> list[str]:
    labels = [part.strip() for part in spec.split(",") if part.strip()]
    if labels and len(labels) != count:
        raise ValueError("label count must match debug dir count")
    if labels:
        return labels
    return ["case_{0}".format(index + 1) for index in range(count)]


def _primary_error(summary: dict[str, Any]) -> str:
    decode_errors = summary.get("decode_errors", {})
    if not isinstance(decode_errors, dict) or not decode_errors:
        return ""
    return sorted(
        decode_errors.items(),
        key=lambda item: (int(item[1]), str(item[0])),
        reverse=True,
    )[0][0]


def _analysis_record(label: str, debug_dir: Path) -> dict[str, Any]:
    summary = analyze_debug_dir(debug_dir)
    return {
        "benchmark_kind": "debug_snapshot_analysis",
        "label": label,
        "debug_dir": str(debug_dir),
        "total_frames": int(summary.get("total_frames", 0)),
        "failed_frames": int(summary.get("failed_frames", 0)),
        "failure_rate": float(summary.get("failure_rate", 0.0)),
        "plane_counts": dict(summary.get("planes", {})),
        "control_kind_counts": dict(summary.get("control_kinds", {})),
        "protocol_path_counts": dict(summary.get("protocol_paths", {})),
        "decode_errors": dict(summary.get("decode_errors", {})),
        "primary_decode_error": _primary_error(summary),
        "control_failure_rate": float(
            summary.get("by_plane", {}).get("control", {}).get("failure_rate", 0.0)
        ),
        "data_failure_rate": float(
            summary.get("by_plane", {}).get("data", {}).get("failure_rate", 0.0)
        ),
        "unknown_failure_rate": float(
            summary.get("by_plane", {}).get("unknown", {}).get("failure_rate", 0.0)
        ),
        "control_payload_parse_failures": dict(summary.get("control_payload_parse_failures", {})),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare receiver debug snapshot directories")
    parser.add_argument(
        "--debug-dirs",
        nargs="+",
        required=True,
        help="one or more receiver debug snapshot directories",
    )
    parser.add_argument(
        "--labels",
        default="",
        help="comma-separated labels matching --debug-dirs order",
    )
    parser.add_argument(
        "--output-json",
        default="",
        help="optional explicit output path; otherwise writes under bench/results",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    debug_dirs = [Path(item) for item in args.debug_dirs]
    labels = _parse_labels(args.labels, len(debug_dirs))
    payload = [
        _analysis_record(label=label, debug_dir=debug_dir)
        for label, debug_dir in zip(labels, debug_dirs)
    ]
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Wrote", output_path)
    else:
        output_path = write_json_result("debug_snapshot_analysis", payload)
        print("Wrote", output_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
