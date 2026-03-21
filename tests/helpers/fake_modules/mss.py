from __future__ import annotations

import numpy as np


class _FakeShot:
    def __init__(self, width: int, height: int, tick: int) -> None:
        self.width = int(width)
        self.height = int(height)
        self._tick = int(tick) & 0xFF
        arr = np.zeros((self.height, self.width, 4), dtype=np.uint8)
        arr[:, :, 0] = self._tick
        arr[:, :, 1] = (self._tick * 3) & 0xFF
        arr[:, :, 2] = (self._tick * 7) & 0xFF
        arr[:, :, 3] = 255
        self._arr = arr
        self.raw = arr.tobytes()

    def __array__(self, dtype=None, copy=None):
        arr = self._arr
        if dtype is not None:
            arr = arr.astype(dtype)
        if copy:
            arr = arr.copy()
        return arr


class mss:
    def __init__(self) -> None:
        self.monitors = [
            {"left": 0, "top": 0, "width": 256, "height": 256},
            {"left": 0, "top": 0, "width": 256, "height": 256},
        ]
        self._tick = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def grab(self, monitor):
        self._tick += 1
        return _FakeShot(monitor["width"], monitor["height"], self._tick)
