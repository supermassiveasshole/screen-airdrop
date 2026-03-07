#!/usr/bin/env python3
"""Aggregate benchmark JSON files and produce markdown summary."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT_ROOT = ROOT / "bench" / "results"


def main() -> int:
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    files = sorted(RESULT_ROOT.glob("benchmark_*.json"))
    rows = []

    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        ok = [x for x in data if x.get("status") == "ok"]
        if not ok:
            continue
        avg_goodput = sum(float(x.get("goodput_kbps", 0.0)) for x in ok) / len(ok)
        avg_bad = sum(float(x.get("bad_frame_rate", 0.0)) for x in ok) / len(ok)
        e2e = sorted(float(x.get("end_to_end_kbps", 0.0)) for x in ok)
        p95_idx = int(round(0.95 * (len(e2e) - 1)))
        p95 = e2e[p95_idx]
        rows.append((f.name, len(data), len(ok), avg_goodput, p95, avg_bad))

    md = ["# Benchmark Summary", "", "| file | total | ok | avg_goodput_kbps | p95_end_to_end_kbps | avg_bad_frame_rate |", "|---|---:|---:|---:|---:|---:|"]
    for r in rows:
        md.append("| {0} | {1} | {2} | {3:.2f} | {4:.2f} | {5:.4f} |".format(*r))

    summary_md = RESULT_ROOT / "summary.md"
    summary_md.write_text("\n".join(md) + "\n", encoding="utf-8")
    print("Wrote", summary_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
