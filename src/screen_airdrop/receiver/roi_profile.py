"""Load/save persistent ROI profiles."""

from __future__ import annotations

import json
import os
import time
from typing import Optional, Tuple


def save_profile(path: str, roi: Tuple[int, int, int, int], monitor_index: int) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    payload = {
        "version": 1,
        "saved_at": int(time.time()),
        "monitor_index": int(monitor_index),
        "roi": {
            "x": int(roi[0]),
            "y": int(roi[1]),
            "w": int(roi[2]),
            "h": int(roi[3]),
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def load_profile(path: str) -> Optional[Tuple[int, int, int, int]]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    roi = payload.get("roi") or {}
    x = int(roi.get("x", 0))
    y = int(roi.get("y", 0))
    w = int(roi.get("w", 0))
    h = int(roi.get("h", 0))
    if w <= 0 or h <= 0:
        return None
    return (x, y, w, h)
