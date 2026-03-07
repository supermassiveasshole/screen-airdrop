#!/usr/bin/env python3
"""Build v3.1 regression case manifest from debug dumps.

Usage:
  uv run python scripts/build_v31_regression_set.py \\
    --debug-dir debug/recv_live_fix \\
    --out tests/fixtures/v31_regression_cases.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug-dir", required=True)
    ap.add_argument("--out", default="tests/fixtures/v31_regression_cases.json")
    ap.add_argument("--grid", default="160x96")
    ap.add_argument("--locator-engine", default="new", choices=["new", "legacy", "auto"])
    args = ap.parse_args()

    debug_dir = Path(args.debug_dir)
    if not debug_dir.exists():
        raise RuntimeError(f"debug dir not found: {debug_dir}")

    gw, gh = [int(p) for p in args.grid.lower().split("x")]

    cases = []
    for jp in sorted(debug_dir.glob("frame_*.json")):
        stem = jp.stem
        raw = debug_dir / f"{stem}.raw.png"
        png = debug_dir / f"{stem}.png"
        frame_path = raw if raw.exists() else png
        if not frame_path.exists():
            continue
        cases.append(
            {
                "id": f"{debug_dir.name}_{stem}",
                "frame_path": frame_path.as_posix(),
                "source_debug_json": jp.as_posix(),
                "grid_w": gw,
                "grid_h": gh,
                "locator_engine": args.locator_engine,
            }
        )

    out = {
        "description": "V3.1 regression set captured from real screen dumps; all listed frames must decode.",
        "default": {
            "grid_w": gw,
            "grid_h": gh,
            "locator_engine": args.locator_engine,
        },
        "cases": cases,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(cases)} cases -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
