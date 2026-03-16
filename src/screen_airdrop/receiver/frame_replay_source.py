"""Replay frame source for deterministic tests and benchmarks."""

from __future__ import annotations

import os
import re
from typing import Generator

import numpy as np


class FrameReplaySource(object):
    def __init__(self, frames_dir: str):
        self.frames_dir = frames_dir

    @staticmethod
    def _sort_key(name: str):
        low = name.lower()
        numeric_match = re.match(r"^(\d+)\.(npy|png)$", low)
        if numeric_match is not None:
            return (0, int(numeric_match.group(1)), low)
        sync_match = re.match(r"^sync_(\d+)\.(npy|png)$", low)
        if sync_match is not None:
            return (1, int(sync_match.group(1)), low)
        epoch_match = re.match(r"^epoch_(\d+)_frame_(\d+)\.(npy|png)$", low)
        if epoch_match is not None:
            return (2, int(epoch_match.group(1)), int(epoch_match.group(2)), low)
        return (3, low)

    def iter_frames(self) -> Generator[np.ndarray, None, None]:
        if not os.path.isdir(self.frames_dir):
            raise RuntimeError("frames dir not found: {0}".format(self.frames_dir))

        files = []
        for name in os.listdir(self.frames_dir):
            low = name.lower()
            if low.endswith(".npy") or low.endswith(".png"):
                files.append(name)
        files.sort(key=self._sort_key)
        if not files:
            raise RuntimeError("no replay frames in: {0}".format(self.frames_dir))

        for name in files:
            full = os.path.join(self.frames_dir, name)
            if name.lower().endswith(".npy"):
                frame = np.load(full)
            else:
                try:
                    import cv2  # pylint: disable=import-outside-toplevel
                except Exception as exc:  # pragma: no cover
                    raise RuntimeError(
                        "opencv-python required to read png replay frames: {0}".format(exc)
                    )
                frame = cv2.imread(full, cv2.IMREAD_COLOR)
                if frame is None:
                    raise RuntimeError("failed to read frame: {0}".format(full))
            yield frame
