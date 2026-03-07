"""OpenCV renderer used by both sender variants.

Synchronous renderer that must be called from the main thread (macOS requirement).
Uses precise timing for frame rate control.
"""

from __future__ import annotations

import time
from typing import Optional


class CV2Renderer(object):
    def __init__(
        self,
        window_name: str,
        fps: int,
        show_overlay: bool = False,
        fullscreen: bool = True,
    ):
        try:
            import cv2  # pylint: disable=import-outside-toplevel
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("opencv-python is required for realtime sender: {0}".format(exc))
        self.cv2 = cv2
        self.window_name = window_name
        self._base_window_name = window_name
        self.show_overlay = show_overlay
        self.fullscreen = fullscreen
        self._frame_interval = 1.0 / max(1, fps)
        self._quit = False
        self._next_tick = time.perf_counter()

        # Create window on main thread
        cv2.namedWindow(self.window_name, cv2.WINDOW_AUTOSIZE)
        if hasattr(cv2, "WND_PROP_ASPECT_RATIO") and hasattr(cv2, "WINDOW_FREERATIO"):
            cv2.setWindowProperty(
                self.window_name,
                cv2.WND_PROP_ASPECT_RATIO,
                cv2.WINDOW_FREERATIO,
            )
        if self.fullscreen and hasattr(cv2, "WND_PROP_FULLSCREEN") and hasattr(cv2, "WINDOW_FULLSCREEN"):
            cv2.setWindowProperty(
                self.window_name,
                cv2.WND_PROP_FULLSCREEN,
                cv2.WINDOW_FULLSCREEN,
            )

    @property
    def stopped(self) -> bool:
        """True if user pressed 'q' or close() was called."""
        return self._quit

    def show(self, frame, overlay_text: Optional[str] = None, pace: bool = True):
        """Display a frame. Returns a command: continue, quit, toggle_pause, reset."""
        if self._quit:
            return "quit"

        cv2 = self.cv2

        if pace:
            # Precise frame-rate pacing
            now = time.perf_counter()
            wait = self._next_tick - now
            if wait > 0.002:
                time.sleep(wait - 0.001)
            while time.perf_counter() < self._next_tick:
                pass
            self._next_tick += self._frame_interval

        render = frame.copy()
        if self.show_overlay and overlay_text:
            cv2.rectangle(render, (8, 8), (1220, 50), (0, 0, 0), thickness=-1)
            cv2.putText(
                render,
                overlay_text,
                (16, 38),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
        cv2.imshow(self.window_name, render)
        key = cv2.waitKey(1 if pace else 30) & 0xFF
        if key == ord("q"):
            self._quit = True
            return "quit"
        if key == 32:
            return "toggle_pause"
        if key in (ord("r"), ord("R")):
            return "reset"
        return "continue"

    def reset_clock(self) -> None:
        self._next_tick = time.perf_counter()

    def close(self):
        self.cv2.destroyWindow(self.window_name)
        time.sleep(0.05)

    def set_window_title(self, suffix: Optional[str] = None) -> None:
        title = self._base_window_name if not suffix else "{0} | {1}".format(self._base_window_name, suffix)
        current_title = getattr(self, "_current_title", self._base_window_name)
        if title == current_title:
            return
        try:
            self.cv2.setWindowTitle(self.window_name, title)
            self._current_title = title
        except Exception:
            pass
