"""Geometry helpers for V3 detector/decoder."""

from __future__ import annotations

from typing import Tuple

import cv2
import numpy as np


def order_quad(pts: np.ndarray) -> np.ndarray:
    # pts shape: (4,2)
    s = pts.sum(axis=1)
    d = pts[:, 0] - pts[:, 1]
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmax(d)]
    bl = pts[np.argmin(d)]
    return np.array([tl, tr, br, bl], dtype=np.float32)


def warp_to_grid(
    frame: np.ndarray,
    quad: np.ndarray,
    grid_w: int,
    grid_h: int,
    cell_px: int = 8,
) -> Tuple[np.ndarray, np.ndarray]:
    src = order_quad(quad.astype(np.float32))
    out_w = grid_w * cell_px
    out_h = grid_h * cell_px
    dst = np.array(
        [
            [0.0, 0.0],
            [float(out_w - 1), 0.0],
            [float(out_w - 1), float(out_h - 1)],
            [0.0, float(out_h - 1)],
        ],
        dtype=np.float32,
    )
    h = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(frame, h, (out_w, out_h), flags=cv2.INTER_NEAREST)
    return warped, h
