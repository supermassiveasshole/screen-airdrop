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

    @classmethod
    def list_frame_paths(cls, frames_dir: str) -> list[str]:
        if not os.path.isdir(frames_dir):
            raise RuntimeError("frames dir not found: {0}".format(frames_dir))

        files = []
        for name in os.listdir(frames_dir):
            low = name.lower()
            if low.endswith(".npy") or low.endswith(".png"):
                files.append(name)
        files.sort(key=cls._sort_key)
        if not files:
            raise RuntimeError("no replay frames in: {0}".format(frames_dir))
        return [os.path.join(frames_dir, name) for name in files]

    @staticmethod
    def load_frame(path: str) -> np.ndarray:
        if str(path).lower().endswith(".npy"):
            return np.load(path)
        try:
            import cv2  # pylint: disable=import-outside-toplevel
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "opencv-python required to read png replay frames: {0}".format(exc)
            )
        frame = cv2.imread(path, cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError("failed to read frame: {0}".format(path))
        return frame

    def frame_paths(self) -> list[str]:
        return self.list_frame_paths(self.frames_dir)

    def infer_frame_size(self) -> tuple[int, int]:
        first_frame = self.load_frame(self.frame_paths()[0])
        height, width = first_frame.shape[:2]
        return int(width), int(height)

    def iter_frames(self) -> Generator[np.ndarray, None, None]:
        for full in self.frame_paths():
            yield self.load_frame(full)
