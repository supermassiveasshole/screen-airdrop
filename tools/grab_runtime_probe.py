"""Probe the receiver's real grab subprocess without decode/coordinator load."""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import queue
import statistics
import time
from pathlib import Path
from typing import Any
from multiprocessing import shared_memory

from screen_airdrop.receiver.runtime.events import FilledSlotEvent
from screen_airdrop.receiver.runtime.workers import _grab_process_main


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
    return ordered[round((len(ordered) - 1) * pct)]


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "mean": round(statistics.fmean(values), 3),
        "p50": round(statistics.median(values), 3),
        "p95": round(_percentile(values, 0.95), 3),
        "max": round(max(values), 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roi", type=_parse_roi, required=True, help="x,y,w,h")
    parser.add_argument("--monitor-index", type=int, default=1)
    parser.add_argument("--fps", type=float, default=55.0)
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--slots", type=int, default=32)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()

    x, y, w, h = args.roi
    ctx = mp.get_context("spawn")
    slot_assign_queue: Any = ctx.Queue()
    descriptor_queue: Any = ctx.Queue()
    stop_event = ctx.Event()

    slot_bytes = w * h * 4
    shms: list[shared_memory.SharedMemory] = []
    generations = [0 for _ in range(args.slots)]
    for slot_id in range(args.slots):
        shm = shared_memory.SharedMemory(create=True, size=slot_bytes)
        shms.append(shm)
        slot_assign_queue.put((slot_id, generations[slot_id]))

    proc = ctx.Process(
        target=_grab_process_main,
        kwargs={
            "slot_assign_queue": slot_assign_queue,
            "descriptor_queue": descriptor_queue,
            "stop_event": stop_event,
            "slot_names": [shm.name for shm in shms],
            "width": w,
            "height": h,
            "target_fps": args.fps,
            "window_title": None,
            "explicit_region": (x, y, w, h),
            "monitor_index": args.monitor_index,
        },
        daemon=False,
    )

    grab_samples: list[float] = []
    copy_samples: list[float] = []
    starvation_count = 0
    slot_wait_samples: list[float] = []
    errors: list[dict[str, Any]] = []

    proc.start()
    end_time = time.time() + args.seconds

    try:
        while time.time() < end_time:
            try:
                item = descriptor_queue.get(timeout=0.25)
            except queue.Empty:
                continue

            if isinstance(item, FilledSlotEvent):
                grab_samples.append(float(item.grab_ms))
                copy_samples.append(float(item.copy_ms))
                descriptor = item.descriptor
                generations[descriptor.slot_id] += 1
                slot_assign_queue.put((descriptor.slot_id, generations[descriptor.slot_id]))
                continue

            if isinstance(item, dict):
                kind = str(item.get("kind", ""))
                if kind == "grab_slot_starvation":
                    starvation_count += 1
                elif kind == "slot_wait_ms":
                    slot_wait_samples.append(float(item.get("value", 0.0)))
                elif kind == "error":
                    errors.append(item)
                continue
    finally:
        stop_event.set()
        slot_assign_queue.put(None)
        proc.join(timeout=5.0)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=1.0)
        try:
            slot_assign_queue.close()
            slot_assign_queue.join_thread()
        except Exception:
            pass
        try:
            descriptor_queue.close()
            descriptor_queue.join_thread()
        except Exception:
            pass
        for shm in shms:
            try:
                shm.close()
            except Exception:
                pass
            try:
                shm.unlink()
            except Exception:
                pass

    result = {
        "roi": {"x": x, "y": y, "w": w, "h": h},
        "monitor_index": args.monitor_index,
        "fps": args.fps,
        "seconds": args.seconds,
        "slots": args.slots,
        "samples": len(grab_samples),
        "proc_exitcode": proc.exitcode,
        "starvations": starvation_count,
        "errors": errors,
        "grab_ms": _summary(grab_samples),
        "copy_ms": _summary(copy_samples),
        "slot_wait_ms": _summary(slot_wait_samples),
    }

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_json:
        args.output_json.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
