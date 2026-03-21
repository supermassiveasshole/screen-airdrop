# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportOptionalMemberAccess=false
"""Compact decoder: locator-engine + payload decode over module matrix."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from screen_airdrop.common.layout_compact import LayoutInfoCompact, LayoutInfoError
from screen_airdrop.common.protocol_basic import (
    DEFAULT_GRID_H,
    DEFAULT_GRID_W,
    ECC_Q,
    FORMAT_SIZE,
    ID_TO_ECC,
    FormatInfoBasic,
    FrameHeaderBasic,
    decode_header_and_payload_bits,
)
from screen_airdrop.receiver.detector_basic import (
    _bbox_from_non_black,
    detect_symbol_bbox,
    detect_symbol_quad,
)
from screen_airdrop.receiver.detector_compact import detect_symbol_quad_compact
from screen_airdrop.receiver.locator.basic import (
    LocateError,
    LocateFailReason,
    LocateQuality,
    LocateResult,
    LocatorConfig,
    _clamp_roi,
    _estimate_timing_phase,
    _quality_confidence,
    _sample_modules_3x3,
    _score_geometry,
    _warp_and_grid,
)
from screen_airdrop.receiver.locator.basic import (
    _bbox_from_quad as _locator_bbox_from_quad,
)
from screen_airdrop.sender.encoder_compact import CompactLayout, build_layout_compact


@dataclass
class DecodeMetaCompact:
    """Compact protocol decode metadata (same structure as basic)."""

    protocol_version_used: int
    locator_engine: str
    confidence: float
    fail_reason: str
    elapsed_ms: float
    legacy_used: bool
    homography_rmse: float
    rs_corrected_symbols: int
    crc_ok: bool
    mask_id: int
    grid_size: str
    det_bbox: tuple[int, int, int, int]
    decode_attempts: int
    det_confidence: float
    new_fail_reason: str
    new_elapsed_ms: float
    legacy_elapsed_ms: float
    locator_debug_artifacts: Dict[str, object]
    locator_warped_preview: Optional[np.ndarray]


def _mask_bit(mask_id: int, x: int, y: int) -> int:
    """Apply QR-style mask pattern (reused from basic)."""
    if mask_id == 0:
        return (x + y) & 1
    if mask_id == 1:
        return y & 1
    if mask_id == 2:
        return x % 3 == 0
    if mask_id == 3:
        return (x + y) % 3 == 0
    if mask_id == 4:
        return ((y // 2) + (x // 3)) & 1
    if mask_id == 5:
        return ((x * y) % 2) + ((x * y) % 3) == 0
    if mask_id == 6:
        return (((x * y) % 2) + ((x * y) % 3)) & 1
    return (((x + y) % 2) + ((x * y) % 3)) & 1


def _read_format_bits(modules: np.ndarray, layout: CompactLayout) -> bytes:
    """Read format information from module matrix."""
    bits = [int(modules[y, x]) for x, y in layout.format_coords]
    unit_len = (FORMAT_SIZE + 2) * 8
    if len(bits) < unit_len:
        raise ValueError("format area too small")
    raw_bits = bits[: unit_len * 3]
    voted = []
    for i in range(unit_len):
        s = 0
        for r in range(3):
            idx = r * unit_len + i
            if idx < len(raw_bits):
                s += raw_bits[idx]
        voted.append(1 if s >= 2 else 0)
    out = bytearray()
    for i in range(0, len(voted), 8):
        v = 0
        for b in voted[i : i + 8]:
            v = (v << 1) | (b & 1)
        out.append(v)
    return bytes(out)


def _read_layout_info(modules: np.ndarray, layout: CompactLayout) -> Optional[LayoutInfoCompact]:
    """Read embedded layout information from sync frames."""
    if not layout.layout_coords:
        return None
    need_bits = 2 * len(LayoutInfoCompact().pack()) * 8
    bits = [int(modules[y, x]) for x, y in layout.layout_coords[:need_bits]]
    if len(bits) < need_bits:
        return None
    voted = []
    half = need_bits // 2
    for i in range(half):
        s = bits[i] + bits[i + half]
        voted.append(1 if s >= 1 else 0)
    raw = bytearray()
    for i in range(0, len(voted), 8):
        v = 0
        for b in voted[i : i + 8]:
            v = (v << 1) | int(b)
        raw.append(v)
    try:
        return LayoutInfoCompact.unpack(bytes(raw))
    except LayoutInfoError:
        return None


def _decode_modules(
    modules: np.ndarray, layout: CompactLayout
) -> Tuple[FrameHeaderBasic, bytes, int]:
    """Decode header and payload from module matrix."""
    mask_candidates: List[int]
    ecc_candidates: List[str]
    try:
        fmt = FormatInfoBasic.unpack(_read_format_bits(modules, layout))
        mask_candidates = [int(fmt.mask_id)]
        ecc_candidates = [ID_TO_ECC.get(int(fmt.ecc_id), ECC_Q)]
    except Exception:
        mask_candidates = [3]
        ecc_candidates = [ECC_Q]

    last_exc = None
    for mask_id in mask_candidates:
        bits = []
        for x, y in layout.data_coords:
            v = int(modules[y, x])
            if _mask_bit(mask_id, x, y):
                v ^= 1
            bits.append(v)
        for ecc in ecc_candidates:
            try:
                header, payload = decode_header_and_payload_bits(bits, ecc_level=ecc)
                return header, payload, mask_id
            except Exception as exc:  # noqa: PERF203
                last_exc = exc
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("compact decode failed")


def _resolve_compact_bbox(
    view: np.ndarray,
    *,
    allow_full_frame: bool,
) -> Optional[Tuple[int, int, int, int]]:
    """Resolve a compact symbol bbox within a local ROI.

    In manual/track ROI flows the symbol may legitimately occupy the entire local view,
    including cases where parts of the quiet zone were cropped away. For compact we accept
    that as a valid prior and let downstream CRC reject bad crops.
    """
    bbox = _bbox_from_non_black(view)
    if bbox is not None:
        return bbox
    det = detect_symbol_bbox(view)
    if det is not None:
        return det.bbox
    if allow_full_frame:
        h, w = view.shape[:2]
        if w >= 64 and h >= 64:
            return (0, 0, int(w), int(h))
    return None


def _bbox_from_dark_pixels(view: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    gray = view.mean(axis=2).astype(np.uint8)
    ys, xs = np.where(gray < 200)
    if len(xs) == 0:
        return None
    x1 = int(np.min(xs))
    x2 = int(np.max(xs))
    y1 = int(np.min(ys))
    y2 = int(np.max(ys))
    if x2 - x1 < 64 or y2 - y1 < 64:
        return None
    return (x1, y1, x2 - x1 + 1, y2 - y1 + 1)


def _bbox_from_quad(
    quad: np.ndarray, frame_shape: Tuple[int, int, int]
) -> tuple[int, int, int, int]:
    """Calculate bounding box from quad."""
    h, w = frame_shape[:2]
    x1 = max(0, int(np.floor(float(np.min(quad[:, 0])))))
    y1 = max(0, int(np.floor(float(np.min(quad[:, 1])))))
    x2 = min(w, int(np.ceil(float(np.max(quad[:, 0])))))
    y2 = min(h, int(np.ceil(float(np.max(quad[:, 1])))))
    return x1, y1, max(1, x2 - x1), max(1, y2 - y1)


def _warp_from_symbol_quad(
    frame: np.ndarray,
    quad_src: np.ndarray,
    layout: CompactLayout,
    warp_size: int,
    dst_rect: Optional[Tuple[int, int, int, int]] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Tuple[int, int, int, int], float]:
    fw = float(layout.frame_w)
    fh = float(layout.frame_h)
    out_w = int(max(64, warp_size))
    out_h = int(max(64, round(out_w * fh / fw)))
    if dst_rect is None:
        dx, dy, dw, dh = 0.0, 0.0, fw, fh
    else:
        dx, dy, dw, dh = [float(v) for v in dst_rect]
    dst = np.array(
        [
            [dx * float(out_w) / fw, dy * float(out_h) / fh],
            [((dx + dw) * float(out_w) / fw) - 1.0, dy * float(out_h) / fh],
            [
                ((dx + dw) * float(out_w) / fw) - 1.0,
                ((dy + dh) * float(out_h) / fh) - 1.0,
            ],
            [dx * float(out_w) / fw, ((dy + dh) * float(out_h) / fh) - 1.0],
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
    return warped, h, inv, (gx0, gy0, gx1 - gx0, gy1 - gy0), 0.0


def _locate_frame_corner_first_compact(
    frame: np.ndarray,
    search_roi: Optional[Tuple[int, int, int, int]],
    cfg: LocatorConfig,
) -> LocateResult | LocateError:
    """Corner-first locator for compact protocol.

    Strategy:
    1. Detect 4 corner finders using 7×7-optimized detection
    2. Build quad from finder centers
    3. Unified warp and sample (like basic)
    4. No dependency on border completeness

    This is the primary path for manual ROI scenarios where borders may be cropped.
    """
    t0 = cv2.getTickCount()

    layout = build_layout_compact(
        grid_w=cfg.grid_w,
        grid_h=cfg.grid_h,
        guard_band=cfg.guard_band,
        corner_size=cfg.corner_size,
    )

    rx, ry, rw, rh = _clamp_roi(search_roi, frame.shape)
    view = frame[ry : ry + rh, rx : rx + rw]
    debug: Dict[str, object] = {"roi_offset": [int(rx), int(ry)], "finder_candidates": []}

    # Phase 1: Try to detect 4 corner finders directly
    quad_result = detect_symbol_quad_compact(view)

    quad = None
    finder_score = 0.0

    if quad_result is not None:
        # Got 4 corners from compact detector
        quad = quad_result.quad.copy()
        quad[:, 0] += float(rx)
        quad[:, 1] += float(ry)
        finder_score = float(quad_result.confidence)

        debug["finder_candidates"].append({
            "bbox": list(_locator_bbox_from_quad(quad, frame.shape)),
            "score": finder_score,
        })

    # Phase 2: Fallback to bbox if corner detection failed
    if quad is None:
        bbox = _bbox_from_non_black(view)
        if bbox is None:
            det = detect_symbol_bbox(view)
            bbox = None if det is None else det.bbox

        if bbox is None:
            elapsed = (cv2.getTickCount() - t0) * 1000.0 / cv2.getTickFrequency()
            return LocateError(LocateFailReason.NO_FINDER, 0.0, elapsed, debug)

        # Build quad from bbox
        bx, by, bw, bh = bbox
        quad = np.array([
            [bx, by],
            [bx + bw - 1, by],
            [bx + bw - 1, by + bh - 1],
            [bx, by + bh - 1],
        ], dtype=np.float32)
        quad[:, 0] += float(rx)
        quad[:, 1] += float(ry)
        finder_score = 0.5

        debug["finder_candidates"].append({
            "bbox": [int(rx + bx), int(ry + by), int(bw), int(bh)],
            "score": finder_score,
        })

    # Phase 3: Validate geometry
    geom_score = _score_geometry(quad)
    if geom_score < 0.2:
        elapsed = (cv2.getTickCount() - t0) * 1000.0 / cv2.getTickFrequency()
        return LocateError(LocateFailReason.BAD_GEOMETRY, finder_score, elapsed, debug)

    # Phase 4: Unified warp and grid (like basic)
    try:
        warped, h, inv, grid_bbox, rmse = _warp_and_grid(
            frame, quad, layout=layout, warp_size=cfg.warp_size
        )
    except Exception:
        elapsed = (cv2.getTickCount() - t0) * 1000.0 / cv2.getTickFrequency()
        return LocateError(LocateFailReason.WARP_FAIL, finder_score, elapsed, debug)

    # Phase 5: Sample modules with timing estimation
    row_score, col_score, timing_score, phi_x, phi_y = _estimate_timing_phase(
        warped, layout, grid_bbox
    )
    timing_used = timing_score >= cfg.timing_threshold

    modules, contrast = _sample_modules_3x3(warped, layout=layout, phi_x=phi_x, phi_y=phi_y)

    # Phase 6: Calculate confidence
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

    elapsed = (cv2.getTickCount() - t0) * 1000.0 / cv2.getTickFrequency()

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

    debug.update({
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
    })

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


def _run_locator(
    frame: np.ndarray,
    locator_engine: str,
    search_roi: Optional[Tuple[int, int, int, int]],
    cfg: LocatorConfig,
) -> Tuple[LocateResult, str, Optional[LocateError], Optional[LocateError]]:
    """Run locator engine using compact layout geometry."""
    def _locate_frame_compact(
        frame: np.ndarray,
        search_roi: Optional[Tuple[int, int, int, int]],
        cfg: LocatorConfig,
    ) -> LocateResult | LocateError:
        t0 = cv2.getTickCount()
        layout = build_layout_compact(
            grid_w=cfg.grid_w,
            grid_h=cfg.grid_h,
            guard_band=cfg.guard_band,
            corner_size=cfg.corner_size,
        )
        rx, ry, rw, rh = _clamp_roi(search_roi, frame.shape)
        view = frame[ry : ry + rh, rx : rx + rw]
        debug: Dict[str, object] = {"roi_offset": [int(rx), int(ry)], "finder_candidates": []}

        bbox_non_black = _resolve_compact_bbox(view, allow_full_frame=search_roi is not None)
        bbox_quad: Optional[np.ndarray] = None
        bbox_confidence = 0.0
        if bbox_non_black is not None:
            bx, by, bw, bh = bbox_non_black
            bbox_quad = np.array(
                [[bx, by], [bx + bw - 1, by], [bx + bw - 1, by + bh - 1], [bx, by + bh - 1]],
                dtype=np.float32,
            )
            bbox_confidence = 0.85

        det = detect_symbol_quad(view) if bbox_quad is None else None

        if det is None and bbox_quad is None:
            b = detect_symbol_bbox(view)
            if b is None:
                elapsed = (cv2.getTickCount() - t0) * 1000.0 / cv2.getTickFrequency()
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

        if bbox_quad is not None:
            quad = bbox_quad.astype(np.float32).copy()
            quad[:, 0] += float(rx)
            quad[:, 1] += float(ry)
            finder_score = bbox_confidence
            geom_score = 1.0
            debug["finder_candidates"].append(
                {"bbox": list(_locator_bbox_from_quad(quad, frame.shape)), "score": float(finder_score)}
            )
            try:
                warped, h, inv, grid_bbox, rmse = _warp_from_symbol_quad(
                    frame, quad, layout=layout, warp_size=cfg.warp_size
                )
            except Exception:
                elapsed = (cv2.getTickCount() - t0) * 1000.0 / cv2.getTickFrequency()
                return LocateError(LocateFailReason.WARP_FAIL, finder_score, elapsed, debug)
        else:
            quad = det.quad.astype(np.float32).copy()
            quad[:, 0] += float(rx)
            quad[:, 1] += float(ry)
            debug["finder_candidates"].append(
                {"bbox": list(_locator_bbox_from_quad(quad, frame.shape)), "score": float(det.confidence)}
            )
            finder_score = float(np.clip(det.confidence, 0.0, 1.0))
            geom_score = _score_geometry(quad)
            if geom_score <= 0.05:
                elapsed = (cv2.getTickCount() - t0) * 1000.0 / cv2.getTickFrequency()
                return LocateError(LocateFailReason.BAD_GEOMETRY, finder_score, elapsed, debug)

            try:
                warped, h, inv, grid_bbox, rmse = _warp_and_grid(
                    frame, quad, layout=layout, warp_size=cfg.warp_size
                )
            except Exception:
                elapsed = (cv2.getTickCount() - t0) * 1000.0 / cv2.getTickFrequency()
                return LocateError(LocateFailReason.WARP_FAIL, finder_score, elapsed, debug)

        row_score, col_score, timing_score, phi_x, phi_y = _estimate_timing_phase(
            warped, layout, grid_bbox
        )
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

        elapsed = (cv2.getTickCount() - t0) * 1000.0 / cv2.getTickFrequency()
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

    def _locate_frame_legacy_compact(
        frame: np.ndarray,
        search_roi: Optional[Tuple[int, int, int, int]],
        cfg: LocatorConfig,
    ) -> LocateResult | LocateError:
        t0 = cv2.getTickCount()
        layout = build_layout_compact(
            grid_w=cfg.grid_w,
            grid_h=cfg.grid_h,
            guard_band=cfg.guard_band,
            corner_size=cfg.corner_size,
        )
        rx, ry, rw, rh = _clamp_roi(search_roi, frame.shape)
        view = frame[ry : ry + rh, rx : rx + rw]

        bbox_non_black = _bbox_from_non_black(view)
        dark_bbox = None if bbox_non_black is not None else _bbox_from_dark_pixels(view)
        use_bbox_quad = bbox_non_black is not None or dark_bbox is not None
        quad_det = detect_symbol_quad(view) if not use_bbox_quad else None

        if bbox_non_black is not None:
            bx, by, bw, bh = bbox_non_black
            quad = np.array(
                [[bx, by], [bx + bw - 1, by], [bx + bw - 1, by + bh - 1], [bx, by + bh - 1]],
                dtype=np.float32,
            )
            quad[:, 0] += float(rx)
            quad[:, 1] += float(ry)
            base_conf = 0.85
            finder_candidates = [{"bbox": [int(quad[0, 0]), int(quad[0, 1]), int(bw), int(bh)], "score": base_conf}]
            warp_to_inner = False
        elif dark_bbox is not None:
            bx, by, bw, bh = dark_bbox
            quad = np.array(
                [[bx, by], [bx + bw - 1, by], [bx + bw - 1, by + bh - 1], [bx, by + bh - 1]],
                dtype=np.float32,
            )
            quad[:, 0] += float(rx)
            quad[:, 1] += float(ry)
            base_conf = 0.8
            finder_candidates = [{"bbox": [int(quad[0, 0]), int(quad[0, 1]), int(bw), int(bh)], "score": base_conf}]
            warp_to_inner = True
        elif quad_det is not None:
            quad = quad_det.quad.astype(np.float32)
            quad[:, 0] += float(rx)
            quad[:, 1] += float(ry)
            base_conf = float(max(0.5, quad_det.confidence))
            finder_candidates = [
                {"bbox": list(_locator_bbox_from_quad(quad, frame.shape)), "score": base_conf}
            ]
            warp_to_inner = False
        else:
            det = detect_symbol_bbox(view)
            if det is None:
                if search_roi is None:
                    elapsed = (cv2.getTickCount() - t0) * 1000.0 / cv2.getTickFrequency()
                    return LocateError(
                        LocateFailReason.NO_FINDER, 0.0, elapsed, {"roi_offset": [rx, ry]}
                    )
                fh, fw = view.shape[:2]
                quad = np.array(
                    [[0, 0], [fw - 1, 0], [fw - 1, fh - 1], [0, fh - 1]],
                    dtype=np.float32,
                )
                quad[:, 0] += float(rx)
                quad[:, 1] += float(ry)
                base_conf = 0.45
                finder_candidates = [
                    {"bbox": [int(rx), int(ry), int(fw), int(fh)], "score": base_conf}
                ]
                warp_to_inner = False
            else:
                bx, by, bw, bh = det.bbox
                bx += rx
                by += ry
                x2 = bx + bw
                y2 = by + bh
                quad = np.array([[bx, by], [x2, by], [x2, y2], [bx, y2]], dtype=np.float32)
                base_conf = float(det.confidence)
                finder_candidates = [{"bbox": [int(bx), int(by), int(bw), int(bh)], "score": base_conf}]
                warp_to_inner = False

        try:
            if bbox_non_black is not None:
                warped, h, inv, grid_bbox, rmse = _warp_from_symbol_quad(
                    frame, quad, layout=layout, warp_size=cfg.warp_size
                )
            elif dark_bbox is not None and warp_to_inner:
                warped, h, inv, grid_bbox, rmse = _warp_from_symbol_quad(
                    frame,
                    quad,
                    layout=layout,
                    warp_size=cfg.warp_size,
                    dst_rect=(
                        int(layout.quiet),
                        int(layout.quiet),
                        int(layout.frame_w - (2 * layout.quiet)),
                        int(layout.frame_h - (2 * layout.quiet)),
                    ),
                )
            else:
                warped, h, inv, grid_bbox, rmse = _warp_and_grid(
                    frame, quad, layout=layout, warp_size=cfg.warp_size
                )
        except Exception:
            elapsed = (cv2.getTickCount() - t0) * 1000.0 / cv2.getTickFrequency()
            return LocateError(
                LocateFailReason.WARP_FAIL, float(base_conf), elapsed, {"roi_offset": [rx, ry]}
            )

        modules, contrast = _sample_modules_3x3(warped, layout=layout, phi_x=0.0, phi_y=0.0)
        confidence = float(np.clip(0.65 * base_conf + 0.35 * contrast, 0.0, 1.0))
        fail = None if confidence >= cfg.confidence_threshold else LocateFailReason.BAD_FINDER_PATTERN
        elapsed = (cv2.getTickCount() - t0) * 1000.0 / cv2.getTickFrequency()

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

    if locator_engine == "new":
        loc = _locate_frame_compact(frame=frame, search_roi=search_roi, cfg=cfg)
        if isinstance(loc, LocateError):
            raise ValueError("locator new failed: {0}".format(loc.fail_reason.value))
        return loc, "new", None, None

    if locator_engine == "legacy":
        loc = _locate_frame_legacy_compact(frame=frame, search_roi=search_roi, cfg=cfg)
        if isinstance(loc, LocateError):
            raise ValueError("locator legacy failed: {0}".format(loc.fail_reason.value))
        return loc, "legacy", None, None

    # auto: prioritize corner-first for all scenarios
    # Corner-first is the primary path for compact (7×7 finders)
    corner_result = _locate_frame_corner_first_compact(frame=frame, search_roi=search_roi, cfg=cfg)

    if isinstance(corner_result, LocateResult):
        if corner_result.fail_reason is None and corner_result.quality.confidence >= cfg.confidence_threshold:
            return corner_result, "corner", None, None

    # Fallback to legacy if corner-first fails or has low confidence
    corner_err: Optional[LocateError] = None
    if isinstance(corner_result, LocateError):
        corner_err = corner_result
    else:
        # Convert low-confidence result to error for fallback
        corner_err = LocateError(
            fail_reason=corner_result.fail_reason or LocateFailReason.BAD_FINDER_PATTERN,
            confidence=corner_result.quality.confidence,
            elapsed_ms=corner_result.elapsed_ms,
            debug_artifacts=corner_result.debug_artifacts,
        )

    legacy_res = _locate_frame_legacy_compact(frame=frame, search_roi=search_roi, cfg=cfg)
    if isinstance(legacy_res, LocateError):
        raise ValueError(
            "locator auto failed: corner={0} legacy={1}".format(
                corner_err.fail_reason.value if corner_err else "NA",
                legacy_res.fail_reason.value,
            )
        )
    return legacy_res, "legacy", corner_err, None


def decode_frame_compact(
    frame: np.ndarray,
    detect_mode: str = "full",
    forced_roi: Optional[Tuple[int, int, int, int]] = None,
    grid_w: int = DEFAULT_GRID_W,
    grid_h: int = DEFAULT_GRID_H,
    guard_band: int = 1,  # Compact default
    corner_size: int = 7,  # Compact default
    roi_only: bool = False,
    manual_strict: bool = False,
    locator_engine: str = "auto",
    locator_confidence_threshold: float = 0.55,
) -> Tuple[FrameHeaderBasic, bytes, DecodeMetaCompact]:
    """Decode frame using compact protocol."""
    if detect_mode not in ("full", "track", "roi"):
        raise ValueError("invalid detect_mode")
    if locator_engine not in ("new", "legacy", "auto"):
        raise ValueError("invalid locator_engine")

    # Maintain external API semantics
    if manual_strict or roi_only:
        if forced_roi is None:
            raise ValueError("manual_strict/roi_only requires forced_roi")
        search_roi = forced_roi
    elif detect_mode == "full":
        search_roi = None
    else:
        search_roi = forced_roi

    cfg = LocatorConfig(
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=guard_band,
        corner_size=corner_size,
        confidence_threshold=locator_confidence_threshold,
    )
    def _decode_from_loc(
        loc: LocateResult,
        used_engine: str,
        new_err: Optional[LocateError],
        legacy_err: Optional[LocateError],
    ) -> Tuple[FrameHeaderBasic, bytes, DecodeMetaCompact]:
        layout = build_layout_compact(
            grid_w=grid_w, grid_h=grid_h, guard_band=guard_band, corner_size=corner_size
        )
        parsed = _read_layout_info(loc.modules, layout)
        if parsed is not None:
            layout = build_layout_compact(
                grid_w=parsed.grid_w,
                grid_h=parsed.grid_h,
                guard_band=parsed.guard,
                corner_size=parsed.finder,
            )

        last_exc: Optional[Exception] = None
        attempts = 0
        for cand in (loc.modules, (1 - loc.modules).astype(np.uint8)):
            attempts += 1
            try:
                header, payload, mask_id = _decode_modules(cand, layout)
                bbox = _bbox_from_quad(loc.quad_src, frame.shape)
                return (
                    header,
                    payload,
                    DecodeMetaCompact(
                        protocol_version_used=40,
                        locator_engine=used_engine,
                        confidence=float(loc.quality.confidence),
                        fail_reason="" if loc.fail_reason is None else loc.fail_reason.value,
                        elapsed_ms=float(loc.elapsed_ms),
                        legacy_used=bool(loc.legacy_used),
                        homography_rmse=float(loc.quality.warp_rmse),
                        rs_corrected_symbols=0,
                        crc_ok=True,
                        mask_id=int(mask_id),
                        grid_size="{0}x{1}".format(layout.grid_w, layout.grid_h),
                        det_bbox=bbox,
                        decode_attempts=attempts,
                        det_confidence=float(loc.quality.confidence),
                        new_fail_reason="" if new_err is None else new_err.fail_reason.value,
                        new_elapsed_ms=0.0 if new_err is None else float(new_err.elapsed_ms),
                        legacy_elapsed_ms=float(loc.elapsed_ms) if loc.legacy_used else 0.0,
                        locator_debug_artifacts=dict(loc.debug_artifacts),
                        locator_warped_preview=loc.warped.copy(),
                    ),
                )
            except Exception as exc:  # noqa: PERF203
                last_exc = exc
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("compact decode failed after all attempts")

    loc, used_engine, new_err, legacy_err = _run_locator(
        frame=frame,
        locator_engine=locator_engine,
        search_roi=search_roi,
        cfg=cfg,
    )
    try:
        return _decode_from_loc(loc, used_engine, new_err, legacy_err)
    except Exception as first_exc:
        if locator_engine == "auto" and used_engine != "legacy":
            legacy_loc, legacy_used_engine, _, _ = _run_locator(
                frame=frame,
                locator_engine="legacy",
                search_roi=search_roi,
                cfg=cfg,
            )
            try:
                return _decode_from_loc(legacy_loc, legacy_used_engine, new_err, None)
            except Exception:
                pass
        raise first_exc
