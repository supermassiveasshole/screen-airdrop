"""Frame drawing utilities for debug visualization."""

from typing import Tuple

import numpy as np


class FrameDrawer:
    """Utility class for drawing debug overlays on frames."""

    @staticmethod
    def draw_rect(
        frame: np.ndarray,
        rect: Tuple[int, int, int, int],
        color: Tuple[int, int, int],
        thickness: int = 2,
    ) -> None:
        """Draw a rectangle on the frame.

        Args:
            frame: Frame to draw on (modified in-place)
            rect: Rectangle (x, y, w, h)
            color: RGB color tuple
            thickness: Line thickness in pixels
        """
        x, y, w, h = rect
        x1 = max(0, int(x))
        y1 = max(0, int(y))
        x2 = min(frame.shape[1] - 1, int(x + w))
        y2 = min(frame.shape[0] - 1, int(y + h))
        if x1 >= x2 or y1 >= y2:
            return
        frame[y1 : min(frame.shape[0], y1 + thickness), x1:x2] = color
        frame[max(0, y2 - thickness) : y2, x1:x2] = color
        frame[y1:y2, x1 : min(frame.shape[1], x1 + thickness)] = color
        frame[y1:y2, max(0, x2 - thickness) : x2] = color

    @staticmethod
    def draw_quad(
        frame: np.ndarray,
        quad: Tuple[
            Tuple[float, float],
            Tuple[float, float],
            Tuple[float, float],
            Tuple[float, float],
        ],
        color: Tuple[int, int, int],
        thickness: int = 2,
    ) -> None:
        """Draw a quadrilateral on the frame.

        Args:
            frame: Frame to draw on (modified in-place)
            quad: Four corner points
            color: RGB color tuple
            thickness: Line thickness in pixels
        """
        pts = [(int(round(p[0])), int(round(p[1]))) for p in quad]
        h, w = frame.shape[:2]
        for i in range(4):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % 4]
            steps = max(abs(x2 - x1), abs(y2 - y1), 1)
            for s in range(steps + 1):
                x = int(round(x1 + (x2 - x1) * (s / float(steps))))
                y = int(round(y1 + (y2 - y1) * (s / float(steps))))
                x = max(0, min(w - 1, x))
                y = max(0, min(h - 1, y))
                y0 = max(0, y - thickness // 2)
                y1b = min(h, y0 + thickness)
                x0 = max(0, x - thickness // 2)
                x1b = min(w, x0 + thickness)
                frame[y0:y1b, x0:x1b] = color

    @staticmethod
    def save_image(path: str, frame: np.ndarray) -> None:
        """Save frame to image file.

        Args:
            path: Output file path
            frame: Frame to save
        """
        try:
            import cv2  # pylint: disable=import-outside-toplevel

            if cv2.imwrite(path, frame):
                return
        except Exception:
            pass

        # Fallback to PIL
        try:
            from PIL import Image  # pylint: disable=import-outside-toplevel

            if frame.ndim == 3 and frame.shape[2] == 3:
                # BGR to RGB
                frame_rgb = frame[:, :, ::-1]
                Image.fromarray(frame_rgb).save(path)
        except Exception:
            pass
