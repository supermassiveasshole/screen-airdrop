#!/usr/bin/env python3
"""Aggregate benchmark JSON files and produce markdown summaries."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT_ROOT = ROOT / "bench" / "results"


def _load_records() -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(RESULT_ROOT.glob("*benchmark_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            continue
        for item in data:
            kind = str(item.get("benchmark_kind", "unknown"))
            item = dict(item)
            item["_source_file"] = path.name
            grouped[kind].append(item)
    return grouped


def main() -> int:
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    grouped = _load_records()
    lines = ["# Benchmark Summary", ""]

    if grouped.get("synthetic_cpu"):
        lines.extend(
            [
                "## Synthetic CPU",
                "",
                "| file | protocol | ecc | payload_mode | success_rate | synthetic_cpu_kib_per_s |",
                "|---|---|---|---|---:|---:|",
            ]
        )
        for item in grouped["synthetic_cpu"]:
            lines.append(
                "| {0} | {1} | {2} | {3} | {4:.2f} | {5:.2f} |".format(
                    item["_source_file"],
                    item["protocol"],
                    item["ecc_level"],
                    item["payload_mode"],
                    float(item["success_rate"]),
                    float(item["synthetic_cpu_kib_per_s"]),
                )
            )
        lines.append("")

    if grouped.get("real_frame_decode"):
        lines.extend(
            [
                "## Real-frame Decode",
                "",
                "| file | protocol | dataset | success_rate | locator_decode_ms_avg | locator_engine_breakdown |",
                "|---|---|---|---:|---:|---|",
            ]
        )
        for item in grouped["real_frame_decode"]:
            lines.append(
                "| {0} | {1} | {2} | {3:.2f} | {4:.2f} | `{5}` |".format(
                    item["_source_file"],
                    item["protocol"],
                    item["dataset_name"],
                    float(item["success_rate"]),
                    float(item["locator_decode_ms_avg"]),
                    json.dumps(item["locator_engine_breakdown"], ensure_ascii=False),
                )
            )
        lines.append("")

    for kind in ("end_to_end_replay", "end_to_end_screen_runbook"):
        if not grouped.get(kind):
            continue
        title = "End-to-End Replay" if kind == "end_to_end_replay" else "End-to-End Screen Runbook"
        lines.extend(
            [
                f"## {title}",
                "",
                "| file | protocol | ecc | payload_mode | payload_bytes | rx_payload_kib_per_s | status |",
                "|---|---|---|---|---:|---:|---|",
            ]
        )
        for item in grouped[kind]:
            lines.append(
                "| {0} | {1} | {2} | {3} | {4} | {5:.2f} | {6} |".format(
                    item["_source_file"],
                    item["protocol"],
                    item.get("ecc_level", ""),
                    item.get("payload_mode", ""),
                    item.get("payload_bytes", 0),
                    float(item.get("rx_payload_kib_per_s", 0.0)),
                    item.get("status", "runbook"),
                )
            )
        lines.append("")

    summary_md = RESULT_ROOT / "summary.md"
    summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Wrote", summary_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
