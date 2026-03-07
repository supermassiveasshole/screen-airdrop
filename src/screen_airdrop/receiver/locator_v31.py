"""V3.1 locator engine with explicit geometry/payload separation."""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np

from screen_airdrop.common.layout_v31 import DEFAULT_FINDER, DEFAULT_GRID_H, DEFAULT_GRID_W, DEFAULT_GUARD
from screen_airdrop.receiver.detector_v3 import detect_symbol_quad
from screen_airdrop.receiver.detector_v31 import detect_symbol_bbox_v31
from screen_airdrop.sender.encoder_v31 import V31Layout, build_layout_v31


class LocateFailReason(str, enum.Enum):
    NO_FINDER = "NO_FINDER"
    BAD_FINDER_PATTERN = "BAD_FINDER_PATTERN"
    BAD_GEOMETRY = "BAD_GEOMETRY"
    WARP_FAIL = "WARP_FAIL"
    TIMING_FAIL = "TIMING_FAIL"
    LOW_CONTRAST = "LOW_CONTRAST"


@dataclass
class LocatorConfig:
    grid_w: int = DEFAULT_GRID_W
    grid_h: int = DEFAULT_GRID_H
    guard_band: int = DEFAULT_GUARD
    corner_size: int = DEFAULT_FINDER
    warp_size: int = 800
    confidence_threshold: float = 0.55
    # pixel-space RMSE in warped plane; 4.0 is too strict for live RDP captures.
    warp_rmse_threshold: float = 160.0
    timing_threshold: float = 0.15
    contrast_threshold: float = 0.05


@dataclass
class LocateQuality:
    finder_score: float
    geom_score: float
    warp_rmse: float
    timing_score: float
    sampling_contrast: float
    confidence: float
    timing_used: bool
    perf_over_budget: bool


@dataclass
class LocateResult:
    quad_src: np.ndarray
    homography: np.ndarray
    homography_inv: np.ndarray
    warped: np.ndarray
    grid_bbox_std: Tuple[int, int, int, int]
    modules: np.ndarray
    quality: LocateQuality
    debug_artifacts: Dict[str, Any]
    elapsed_ms: float
    fail_reason: Optional[LocateFailReason] = None
    legacy_used: bool = False


@dataclass
class LocateError:
    fail_reason: LocateFailReason
    confidence: float
    elapsed_ms: float
    debug_artifacts: Dict[str, Any]


def _clamp_roi(
    roi: Optional[Tuple[int, int, int, int]], frame_shape: Tuple[int, int, int]
) -> Tuple[int, int, int, int]:
    h, w = frame_shape[:2]
    if roi is None:
        return (0, 0, w, h)
    x, y, rw, rh = roi
    x1 = max(0, int(x))
    y1 = max(0, int(y))
    x2 = min(w, x1 + max(1, int(rw)))
    y2 = min(h, y1 + max(1, int(rh)))
    if x2 <= x1 or y2 <= y1:
        return (0, 0, w, h)
    return (x1, y1, x2 - x1, y2 - y1)


def _score_geometry(quad: np.ndarray) -> float:
    tl, tr, br, bl = quad
    top = float(np.linalg.norm(tr - tl))
    bottom = float(np.linalg.norm(br - bl))
    left = float(np.linalg.norm(bl - tl))
    right = float(np.linalg.norm(br - tr))
    mn = min(top, bottom, left, right)
    if mn <= 1e-6:
        return 0.0
    sym = min(top, bottom) / max(top, bottom)
    sym *= min(left, right) / max(left, right)
    v1 = tr - tl
    v2 = bl - tl
    area = abs(float((v1[0] * v2[1]) - (v1[1] * v2[0])))
    return float(max(0.0, min(1.0, sym * min(1.0, area / 5000.0))))


def _warp_and_grid(
    frame: np.ndarray,
    quad_src: np.ndarray,
    layout: V31Layout,
    warp_size: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Tuple[int, int, int, int], float]:
    fw = float(layout.frame_w)
    fh = float(layout.frame_h)
    out_w = int(max(64, warp_size))
    out_h = int(max(64, round(out_w * fh / fw)))

    c2 = int(layout.finder // 2)

    def _module_to_px(mx: int, my: int) -> Tuple[float, float]:
        return ((mx + 0.5) * (float(out_w) / fw), (my + 0.5) * (float(out_h) / fh))

    dst = np.array(
        [
            _module_to_px(layout.quiet + c2, layout.quiet + c2),
            _module_to_px(layout.frame_w - layout.quiet - c2 - 1, layout.quiet + c2),
            _module_to_px(layout.frame_w - layout.quiet - c2 - 1, layout.frame_h - layout.quiet - c2 - 1),
            _module_to_px(layout.quiet + c2, layout.frame_h - layout.quiet - c2 - 1),
        ],
        dtype=np.float32,
    )
    src = quad_src.astype(np.float32)
    h = cv2.getPerspectiveTransform(src, dst)
    inv = np.linalg.inv(h)
    warped = cv2.warpPerspective(frame, h, (out_w, out_h), flags=cv2.INTER_LINEAR)

    sx = float(out_w) / fw
    sy = float(out_h) / fh
    gx0 = int(round(layout.grid_x0 * sx))
    gy0 = int(round(layout.grid_y0 * sy))
    gx1 = int(round((layout.grid_x1 + 1) * sx))
    gy1 = int(round((layout.grid_y1 + 1) * sy))
    gx0 = max(0, min(out_w - 1, gx0))
    gy0 = max(0, min(out_h - 1, gy0))
    gx1 = max(gx0 + 1, min(out_w, gx1))
    gy1 = max(gy0 + 1, min(out_h, gy1))

    # Estimate full symbol corners from finder-center quad, then evaluate
    # reprojection error against warped image corners.
    c2f = float(c2)
    mx_tl = float(layout.quiet) + c2f
    my_tl = float(layout.quiet) + c2f
    mx_tr = float(layout.frame_w - layout.quiet - c2 - 1)
    my_bl = float(layout.frame_h - layout.quiet - c2 - 1)
    dx_mod = max(1e-6, mx_tr - mx_tl)
    dy_mod = max(1e-6, my_bl - my_tl)
    ux = (src[1] - src[0]) / dx_mod
    uy = (src[3] - src[0]) / dy_mod
    sym_tl = src[0] - (ux * mx_tl) - (uy * my_tl)
    sym_tr = src[0] + (ux * (fw - 1.0 - mx_tl)) - (uy * my_tl)
    sym_br = src[0] + (ux * (fw - 1.0 - mx_tl)) + (uy * (fh - 1.0 - my_tl))
    sym_bl = src[0] - (ux * mx_tl) + (uy * (fh - 1.0 - my_tl))
    sym_src = np.array([sym_tl, sym_tr, sym_br, sym_bl], dtype=np.float32)
    dst_corners = np.array(
        [[0.0, 0.0], [float(out_w - 1), 0.0], [float(out_w - 1), float(out_h - 1)], [0.0, float(out_h - 1)]],
        dtype=np.float32,
    )
    proj = cv2.perspectiveTransform(sym_src.reshape(1, 4, 2), h).reshape(4, 2)
    err = proj - dst_corners
    rmse = float(np.sqrt(np.mean(np.sum(err * err, axis=1))))
    return warped, h, inv, (gx0, gy0, gx1 - gx0, gy1 - gy0), rmse


def _estimate_timing_phase(
    warped: np.ndarray,
    layout: V31Layout,
    grid_bbox: Tuple[int, int, int, int],
) -> Tuple[float, float, float, float, float]:
    x, y, w, h = grid_bbox
    gray = warped.mean(axis=2).astype(np.float32) / 255.0
    if w < 8 or h < 8:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    cell_w = float(warped.shape[1]) / float(layout.frame_w)
    cell_h = float(warped.shape[0]) / float(layout.frame_h)
    rail_y = max(0, min(gray.shape[0] - 1, int(round((layout.grid_y0 - 0.5) * cell_h))))
    rail_x = max(0, min(gray.shape[1] - 1, int(round((layout.grid_x0 - 0.5) * cell_w))))

    def _score_axis(axis: str) -> Tuple[float, float]:
        best_phi = 0.0
        best_score = -1.0
        for phi in np.linspace(-0.45, 0.45, 19):
            vals = []
            if axis == "x":
                for i in range(layout.grid_w):
                    px = int(round((layout.grid_x0 + i + 0.5 + phi) * cell_w))
                    px = max(0, min(gray.shape[1] - 1, px))
                    vals.append(float(gray[rail_y, px]))
            else:
                for j in range(layout.grid_h):
                    py = int(round((layout.grid_y0 + j + 0.5 + phi) * cell_h))
                    py = max(0, min(gray.shape[0] - 1, py))
                    vals.append(float(gray[py, rail_x]))
            if len(vals) < 4:
                continue
            arr = np.asarray(vals, dtype=np.float32)
            even = float(np.mean(arr[0::2]))
            odd = float(np.mean(arr[1::2]))
            score = abs(even - odd)
            if score > best_score:
                best_score = score
                best_phi = float(phi)
        return best_phi, float(np.clip(best_score * 3.0, 0.0, 1.0))

    phi_x, row_score = _score_axis("x")
    phi_y, col_score = _score_axis("y")
    timing_score = min(row_score, col_score)
    return row_score, col_score, timing_score, phi_x, phi_y


def _sample_modules_3x3(warped: np.ndarray, layout: V31Layout, phi_x: float, phi_y: float) -> Tuple[np.ndarray, float]:
    gray = warped.mean(axis=2).astype(np.float32) / 255.0
    gray_u8 = (gray * 255.0).astype(np.uint8)
    thr_u8, _ = cv2.threshold(gray_u8, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    thr = float(thr_u8) / 255.0
    cell_w = float(warped.shape[1]) / float(layout.frame_w)
    cell_h = float(warped.shape[0]) / float(layout.frame_h)
    h_max = gray.shape[0] - 1
    w_max = gray.shape[1] - 1

    # Pre-compute center coords for every module cell: shapes (frame_h,) and (frame_w,)
    cy_base = (np.arange(layout.frame_h, dtype=np.float32) + 0.5 + phi_y) * cell_h
    cx_base = (np.arange(layout.frame_w, dtype=np.float32) + 0.5 + phi_x) * cell_w

    # Accumulate votes from all 9 sub-cell offsets fully vectorised.
    # For each offset (oy, ox), gather gray[py[j], px[i]] for all (j,i) at once.
    offsets = [(-0.25, -0.25), (-0.25, 0.0), (-0.25, 0.25),
               (0.0,  -0.25), (0.0,  0.0), (0.0,  0.25),
               (0.25, -0.25), (0.25, 0.0), (0.25, 0.25)]
    vote_sum = np.zeros((layout.frame_h, layout.frame_w), dtype=np.float32)
    for oy, ox in offsets:
        py = np.clip(np.round(cy_base + oy * cell_h).astype(np.int32), 0, h_max)  # (frame_h,)
        px = np.clip(np.round(cx_base + ox * cell_w).astype(np.int32), 0, w_max)  # (frame_w,)
        vote_sum += gray[py[:, None], px[None, :]]   # (frame_h, frame_w) gather

    modules = (vote_sum >= thr * 9.0).view(np.uint8)

    # Contrast: std of per-cell mean values in the data grid region
    grid_means = vote_sum[layout.grid_y0:layout.grid_y1 + 1,
                          layout.grid_x0:layout.grid_x1 + 1] / 9.0
    contrast = float(np.clip(float(np.std(grid_means)) * 2.0, 0.0, 1.0))
    return modules, contrast


def _bbox_from_quad(quad: np.ndarray, frame_shape: Tuple[int, int, int]) -> Tuple[int, int, int, int]:
    h, w = frame_shape[:2]
    x1 = max(0, int(np.floor(float(np.min(quad[:, 0])))))
    y1 = max(0, int(np.floor(float(np.min(quad[:, 1])))))
    x2 = min(w, int(np.ceil(float(np.max(quad[:, 0])))))
    y2 = min(h, int(np.ceil(float(np.max(quad[:, 1])))))
    return (x1, y1, max(1, x2 - x1), max(1, y2 - y1))


def _quality_confidence(
    finder_score: float,
    geom_score: float,
    warp_rmse: float,
    timing_score: float,
    contrast: float,
    rmse_threshold: float,
) -> float:
    rmse_norm = min(1.0, max(0.0, warp_rmse / max(1e-6, rmse_threshold)))
    return float(
        0.30 * finder_score
        + 0.25 * geom_score
        + 0.20 * (1.0 - rmse_norm)
        + 0.15 * timing_score
        + 0.10 * contrast
    )


def locate_frame(
    frame: np.ndarray,
    search_roi: Optional[Tuple[int, int, int, int]] = None,
    config: Optional[LocatorConfig] = None,
) -> LocateResult | LocateError:
    t0 = time.perf_counter()
    cfg = config if config is not None else LocatorConfig()
    layout = build_layout_v31(
        grid_w=cfg.grid_w,
        grid_h=cfg.grid_h,
        guard_band=cfg.guard_band,
        corner_size=cfg.corner_size,
    )

    rx, ry, rw, rh = _clamp_roi(search_roi, frame.shape)
    view = frame[ry : ry + rh, rx : rx + rw]
    debug: Dict[str, Any] = {"roi_offset": [int(rx), int(ry)], "finder_candidates": []}

    det = detect_symbol_quad(view)
    if det is None:
        # Fallback: still keep ROI semantics, but allow bbox-based quad synthesis.
        b = detect_symbol_bbox_v31(view)
        if b is None:
            elapsed = (time.perf_counter() - t0) * 1000.0
            return LocateError(LocateFailReason.NO_FINDER, 0.0, elapsed, debug)
        bx, by, bw, bh = b.bbox
        det_quad = np.array(
            [[bx, by], [bx + bw, by], [bx + bw, by + bh], [bx, by + bh]],
            dtype=np.float32,
        )
        class _Tmp:
            quad = det_quad
            confidence = float(max(0.5, b.confidence))
        det = _Tmp()

    quad = det.quad.astype(np.float32).copy()
    quad[:, 0] += float(rx)
    quad[:, 1] += float(ry)
    debug["finder_candidates"].append({"bbox": list(_bbox_from_quad(quad, frame.shape)), "score": float(det.confidence)})
    finder_score = float(np.clip(det.confidence, 0.0, 1.0))
    geom_score = _score_geometry(quad)
    if geom_score <= 0.05:
        elapsed = (time.perf_counter() - t0) * 1000.0
        return LocateError(LocateFailReason.BAD_GEOMETRY, finder_score, elapsed, debug)

    try:
        warped, h, inv, grid_bbox, rmse = _warp_and_grid(frame, quad, layout=layout, warp_size=cfg.warp_size)
    except Exception:
        elapsed = (time.perf_counter() - t0) * 1000.0
        return LocateError(LocateFailReason.WARP_FAIL, finder_score, elapsed, debug)

    row_score, col_score, timing_score, phi_x, phi_y = _estimate_timing_phase(warped, layout, grid_bbox)
    timing_used = timing_score >= cfg.timing_threshold

    modules, contrast = _sample_modules_3x3(warped, layout=layout, phi_x=phi_x, phi_y=phi_y)
    confidence = _quality_confidence(
        finder_score=finder_score,
        geom_score=geom_score,
        warp_rmse=rmse,
        timing_score=timing_score,
        contrast=contrast,
        rmse_threshold=cfg.warp_rmse_threshold,
    )
    fail_reason: Optional[LocateFailReason] = None
    if not timing_used:
        fail_reason = LocateFailReason.TIMING_FAIL
    if contrast < cfg.contrast_threshold:
        fail_reason = LocateFailReason.LOW_CONTRAST
    if confidence < cfg.confidence_threshold and fail_reason is None:
        fail_reason = LocateFailReason.BAD_FINDER_PATTERN

    elapsed = (time.perf_counter() - t0) * 1000.0
    quality = LocateQuality(
        finder_score=finder_score,
        geom_score=geom_score,
        warp_rmse=rmse,
        timing_score=timing_score,
        sampling_contrast=contrast,
        confidence=confidence,
        timing_used=timing_used,
        perf_over_budget=elapsed > 40.0,
    )
    debug.update(
        {
            "quad_src": quad.astype(float).tolist(),
            "grid_bbox_std": [int(v) for v in grid_bbox],
            "timing_row_score": float(row_score),
            "timing_col_score": float(col_score),
            "timing_score": float(timing_score),
            "timing_phi_x": float(phi_x),
            "timing_phi_y": float(phi_y),
            "warp_rmse": float(rmse),
            "confidence": float(confidence),
            "fail_reason": None if fail_reason is None else str(fail_reason.value),
        }
    )
    return LocateResult(
        quad_src=quad,
        homography=h,
        homography_inv=inv,
        warped=warped,
        grid_bbox_std=grid_bbox,
        modules=modules,
        quality=quality,
        debug_artifacts=debug,
        elapsed_ms=elapsed,
        fail_reason=fail_reason,
        legacy_used=False,
    )


def locate_frame_legacy(
    frame: np.ndarray,
    search_roi: Optional[Tuple[int, int, int, int]] = None,
    config: Optional[LocatorConfig] = None,
) -> LocateResult | LocateError:
    t0 = time.perf_counter()
    cfg = config if config is not None else LocatorConfig()
    layout = build_layout_v31(
        grid_w=cfg.grid_w,
        grid_h=cfg.grid_h,
        guard_band=cfg.guard_band,
        corner_size=cfg.corner_size,
    )
    rx, ry, rw, rh = _clamp_roi(search_roi, frame.shape)
    view = frame[ry : ry + rh, rx : rx + rw]

    quad_det = detect_symbol_quad(view)
    if quad_det is not None:
        quad = quad_det.quad.astype(np.float32)
        quad[:, 0] += float(rx)
        quad[:, 1] += float(ry)
        base_conf = float(max(0.5, quad_det.confidence))
        finder_candidates = [{"bbox": list(_bbox_from_quad(quad, frame.shape)), "score": base_conf}]
    else:
        det = detect_symbol_bbox_v31(view)
        if det is None:
            elapsed = (time.perf_counter() - t0) * 1000.0
            return LocateError(LocateFailReason.NO_FINDER, 0.0, elapsed, {"roi_offset": [rx, ry]})
        bx, by, bw, bh = det.bbox
        bx += rx
        by += ry
        x2 = bx + bw
        y2 = by + bh
        quad = np.array([[bx, by], [x2, by], [x2, y2], [bx, y2]], dtype=np.float32)
        base_conf = float(det.confidence)
        finder_candidates = [{"bbox": [int(bx), int(by), int(bw), int(bh)], "score": base_conf}]

    try:
        warped, h, inv, grid_bbox, rmse = _warp_and_grid(frame, quad, layout=layout, warp_size=cfg.warp_size)
    except Exception:
        elapsed = (time.perf_counter() - t0) * 1000.0
        return LocateError(LocateFailReason.WARP_FAIL, float(base_conf), elapsed, {"roi_offset": [rx, ry]})

    modules, contrast = _sample_modules_3x3(warped, layout=layout, phi_x=0.0, phi_y=0.0)
    confidence = float(np.clip(0.65 * base_conf + 0.35 * contrast, 0.0, 1.0))
    fail = None if confidence >= cfg.confidence_threshold else LocateFailReason.BAD_FINDER_PATTERN
    elapsed = (time.perf_counter() - t0) * 1000.0

    quality = LocateQuality(
        finder_score=float(base_conf),
        geom_score=0.6,
        warp_rmse=rmse,
        timing_score=0.5,
        sampling_contrast=contrast,
        confidence=confidence,
        timing_used=False,
        perf_over_budget=elapsed > 40.0,
    )
    return LocateResult(
        quad_src=quad,
        homography=h,
        homography_inv=inv,
        warped=warped,
        grid_bbox_std=grid_bbox,
        modules=modules,
        quality=quality,
        debug_artifacts={
            "roi_offset": [int(rx), int(ry)],
            "finder_candidates": finder_candidates,
            "quad_src": quad.astype(float).tolist(),
            "grid_bbox_std": [int(v) for v in grid_bbox],
            "warp_rmse": float(rmse),
            "timing_score": 0.0,
            "confidence": float(confidence),
            "fail_reason": None if fail is None else str(fail.value),
        },
        elapsed_ms=elapsed,
        fail_reason=fail,
        legacy_used=True,
    )
