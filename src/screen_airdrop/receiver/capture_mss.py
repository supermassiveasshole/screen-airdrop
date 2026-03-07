"""Realtime capture from screen using mss."""

from __future__ import annotations

import time
from typing import Generator, Optional, Tuple

import cv2
import numpy as np

from screen_airdrop.receiver.window_locator import resolve_window_region


def get_monitor_region(monitor_index: int) -> Tuple[int, int, int, int]:
    try:
        import mss  # pylint: disable=import-outside-toplevel
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("mss is required for receiver capture: {0}".format(exc))

    with mss.mss() as sct:
        if monitor_index <= 0 or monitor_index >= len(sct.monitors):
            raise RuntimeError(
                "invalid monitor index {0}; available monitors: 1..{1}".format(
                    monitor_index,
                    len(sct.monitors) - 1,
                )
            )
        m = sct.monitors[monitor_index]
        return (int(m["left"]), int(m["top"]), int(m["width"]), int(m["height"]))


class ScreenCapture(object):
    def __init__(
        self,
        window_title: Optional[str],
        region: Optional[Tuple[int, int, int, int]] = None,
        monitor_index: int = 1,
        frame_diff_threshold: float = 0.015,
        target_fps: float = 15.0,
    ):
        self.window_title = window_title
        self.region = region
        self.monitor_index = monitor_index
        self.active_region = None  # type: Optional[Tuple[int, int, int, int]]
        self.frame_diff_threshold = frame_diff_threshold
        self.target_fps = target_fps
        try:
            import mss  # pylint: disable=import-outside-toplevel
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("mss is required for receiver capture: {0}".format(exc))
        self._mss_mod = mss

    def iter_frames(self) -> Generator[np.ndarray, None, None]:
        with self._mss_mod.mss() as sct:
            monitor_region = get_monitor_region(self.monitor_index)
            x, y, w, h = resolve_window_region(
                window_title=self.window_title,
                explicit_region=self.region,
                monitor_region=monitor_region,
            )
            self.active_region = (x, y, w, h)
            monitor = {"left": x, "top": y, "width": w, "height": h}
            prev_frame = None
            frame_interval = 1.0 / self.target_fps if self.target_fps > 0 else 0.0
            last_yield = time.perf_counter()

            while True:
                shot = sct.grab(monitor)
                frame = screenshot_to_bgr(shot)

                # Frame difference check
                if prev_frame is not None:
                    diff = compute_frame_diff(frame, prev_frame)
                    if diff < self.frame_diff_threshold:
                        time.sleep(0.005)
                        continue

                # Rate limiting
                now = time.perf_counter()
                elapsed = now - last_yield
                if frame_interval > 0 and elapsed < frame_interval:
                    time.sleep(frame_interval - elapsed)

                prev_frame = frame
                last_yield = time.perf_counter()
                yield frame


def screenshot_to_bgr(shot) -> np.ndarray:
    """Copy only the visible BGR channels from an MSS screenshot."""
    bgra = np.asarray(shot)
    return bgra[:, :, :3].copy()


def compute_frame_diff(frame: np.ndarray, prev_frame: np.ndarray, step: int = 4) -> float:
    """Fast normalized frame-difference for dedup decisions."""
    if step > 1:
        frame_view = frame[::step, ::step]
        prev_view = prev_frame[::step, ::step]
    else:
        frame_view = frame
        prev_view = prev_frame
    return float(cv2.absdiff(frame_view, prev_view).mean()) / 255.0
