#!/usr/bin/env python3
"""Analyze receiver debug snapshots and summarize decode behavior."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        if isinstance(item, dict):
            records.append(item)
    return records


def _frame_meta_records(debug_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(debug_dir.glob("frame_*.json")):
        data = _load_json(path)
        if data:
            records.append(data)
    return records


def _rate(failures: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return float(failures) / float(total)


def _summarize_bucket(values: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(values)
    failures = sum(1 for value in values if str(value.get("decode_error", "")))
    return {
        "frames": total,
        "failure_frames": failures,
        "failure_rate": _rate(failures, total),
    }


def analyze_debug_dir(debug_dir: Path) -> dict[str, Any]:
    summary = _load_json(debug_dir / "summary.json")
    index_records = _load_jsonl(debug_dir / "index_all.jsonl")
    frame_records = _frame_meta_records(debug_dir)

    if not index_records and frame_records:
        index_records = [
            {
                "frame_index": int(item.get("frame_index", 0)),
                "plane": str(item.get("decoded_plane", "unknown") or "unknown"),
                "control_family": str(item.get("decoded_control_family", "") or ""),
                "control_kind": str(item.get("decoded_control_kind", "") or ""),
                "protocol_path_used": str(item.get("protocol_path_used", "") or ""),
                "decode_error": str(item.get("decode_error", "") or ""),
                "frame_json": "frame_{0:05d}.json".format(int(item.get("frame_index", 0))),
            }
            for item in frame_records
        ]

    frames_by_plane: dict[str, list[dict[str, Any]]] = {}
    frames_by_control_kind: dict[str, list[dict[str, Any]]] = {}
    frames_by_protocol: dict[str, list[dict[str, Any]]] = {}
    decode_errors: Counter[str] = Counter()

    for record in index_records:
        plane = str(record.get("plane", "unknown") or "unknown")
        control_kind = str(record.get("control_kind", "") or "")
        protocol_path = str(record.get("protocol_path_used", "unknown") or "unknown")
        decode_error = str(record.get("decode_error", "") or "")
        frames_by_plane.setdefault(plane, []).append(record)
        frames_by_protocol.setdefault(protocol_path, []).append(record)
        if control_kind:
            frames_by_control_kind.setdefault(control_kind, []).append(record)
        if decode_error:
            decode_errors[decode_error] += 1

    control_payload_parse_failures: Counter[str] = Counter()
    for frame_meta in frame_records:
        control_kind = str(frame_meta.get("decoded_control_kind", "") or "")
        payload = frame_meta.get("decoded_control_payload")
        if not control_kind or not isinstance(payload, dict):
            continue
        if str(payload.get("decode_error", "")) == "control_payload_parse_failed":
            control_payload_parse_failures[control_kind] += 1

    total_frames = len(index_records) if index_records else int(summary.get("total_frames", 0))
    failed_frames = sum(decode_errors.values())

    result = {
        "debug_dir": str(debug_dir),
        "total_frames": total_frames,
        "failed_frames": failed_frames,
        "failure_rate": _rate(failed_frames, total_frames),
        "planes": dict(summary.get("planes", {})) if isinstance(summary.get("planes"), dict) else {},
        "control_kinds": dict(summary.get("control_kinds", {}))
        if isinstance(summary.get("control_kinds"), dict)
        else {},
        "protocol_paths": dict(summary.get("protocol_paths", {}))
        if isinstance(summary.get("protocol_paths"), dict)
        else {},
        "decode_errors": dict(sorted(decode_errors.items())),
        "by_plane": {
            key: _summarize_bucket(value)
            for key, value in sorted(frames_by_plane.items())
        },
        "by_control_kind": {
            key: _summarize_bucket(value)
            for key, value in sorted(frames_by_control_kind.items())
        },
        "by_protocol_path": {
            key: _summarize_bucket(value)
            for key, value in sorted(frames_by_protocol.items())
        },
        "control_payload_parse_failures": dict(sorted(control_payload_parse_failures.items())),
    }
    return result


def _render_text(summary: dict[str, Any]) -> str:
    lines = [
        "Debug Snapshot Analysis",
        "debug_dir={0}".format(summary["debug_dir"]),
        "total_frames={0} failed_frames={1} failure_rate={2:.4f}".format(
            int(summary["total_frames"]),
            int(summary["failed_frames"]),
            float(summary["failure_rate"]),
        ),
        "",
        "By Plane",
    ]
    for key, bucket in summary["by_plane"].items():
        lines.append(
            "{0}: frames={1} failure_frames={2} failure_rate={3:.4f}".format(
                key,
                int(bucket["frames"]),
                int(bucket["failure_frames"]),
                float(bucket["failure_rate"]),
            )
        )
    lines.append("")
    lines.append("By Control Kind")
    if summary["by_control_kind"]:
        for key, bucket in summary["by_control_kind"].items():
            lines.append(
                "{0}: frames={1} failure_frames={2} failure_rate={3:.4f}".format(
                    key,
                    int(bucket["frames"]),
                    int(bucket["failure_frames"]),
                    float(bucket["failure_rate"]),
                )
            )
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("Decode Errors")
    if summary["decode_errors"]:
        for key, count in summary["decode_errors"].items():
            lines.append("{0}: {1}".format(key, int(count)))
    else:
        lines.append("(none)")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze receiver debug snapshots")
    parser.add_argument("--debug-dir", required=True, help="receiver debug snapshot directory")
    parser.add_argument("--output-json", default=None, help="optional path to write JSON summary")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    debug_dir = Path(args.debug_dir)
    summary = analyze_debug_dir(debug_dir)
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(_render_text(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
