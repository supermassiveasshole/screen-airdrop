#!/usr/bin/env python3
"""Probe MSS behavior inside a spawned child process."""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import queue
import time


def _worker(region: dict[str, int], out_q) -> None:
    import mss

    start = time.perf_counter()
    with mss.mss() as sct:
        for i in range(240):
            t0 = time.perf_counter()
            shot = sct.grab(region)
            t1 = time.perf_counter()
            out_q.put(
                {
                    "i": i,
                    "grab_ms": round((t1 - t0) * 1000.0, 3),
                    "sha16": hashlib.sha256(bytes(shot.raw)).hexdigest()[:16],
                    "elapsed_s": round(t1 - start, 3),
                }
            )
            time.sleep(1.0 / 55.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--x", type=int, required=True)
    parser.add_argument("--y", type=int, required=True)
    parser.add_argument("--w", type=int, required=True)
    parser.add_argument("--h", type=int, required=True)
    args = parser.parse_args()

    region = {"left": args.x, "top": args.y, "width": args.w, "height": args.h}
    ctx = mp.get_context("spawn")
    out_q = ctx.Queue()
    proc = ctx.Process(target=_worker, args=(region, out_q))
    proc.start()

    rows = []
    stalled = False
    while len(rows) < 240 and proc.is_alive():
        try:
            rows.append(out_q.get(timeout=1.5))
        except queue.Empty:
            stalled = True
            break

    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=2.0)

    print(
        json.dumps(
            {
                "received": len(rows),
                "stalled": stalled,
                "first5": rows[:5],
                "last10": rows[-10:],
                "unique_hashes": len({x["sha16"] for x in rows}),
                "max_grab_ms": max((x["grab_ms"] for x in rows), default=None),
                "exitcode": proc.exitcode,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
