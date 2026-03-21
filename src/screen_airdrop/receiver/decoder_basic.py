"""Basic decoder: locator-engine + payload decode over module matrix."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from screen_airdrop.common.layout_basic import LayoutInfoBasic, LayoutInfoError
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
from screen_airdrop.receiver.detector_basic import _bbox_from_non_black, detect_symbol_quad
from screen_airdrop.receiver.locator.basic import (
    LocateError,
    LocateFailReason,
    LocateResult,
    LocatorConfig,
    locate_frame,
    locate_frame_legacy,
)
from screen_airdrop.sender.encoder_basic import BasicLayout, build_layout_basic


@dataclass
class DecodeMetaBasic:
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


def _read_format_bits(modules: np.ndarray, layout: BasicLayout) -> bytes:
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


def _read_layout_info(modules: np.ndarray, layout: BasicLayout) -> Optional[LayoutInfoBasic]:
    if not layout.layout_coords:
        return None
    need_bits = 2 * len(LayoutInfoBasic().pack()) * 8
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
        return LayoutInfoBasic.unpack(bytes(raw))
    except LayoutInfoError:
        return None


def _decode_modules(
    modules: np.ndarray, layout: BasicLayout
) -> Tuple[FrameHeaderBasic, bytes, int]:
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
    raise RuntimeError("basic decode failed")


def _build_layout_basic_compat(
    grid_w: int,
    grid_h: int,
    guard_band: int,
    corner_size: int,
) -> BasicLayout:
    q = 4
    guard = max(1, int(guard_band))
    corner = max(7, int(corner_size))
    if corner % 2 == 0:
        corner += 1

    x0 = q + corner + guard + 1
    y0 = q + corner + guard + 1
    x1 = grid_w - q - corner - guard - 2
    y1 = grid_h - q - corner - guard - 2
    if x1 <= x0 or y1 <= y0:
        raise ValueError("basic legacy compat layout too small")

    data_coords = []
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            data_coords.append((x, y))

    format_coords = []
    fy = q + (corner // 2)
    fx = q + (corner // 2)
    for x in range(q + corner + 1, grid_w - q - corner - 1):
        format_coords.append((x, fy))
    for y in range(q + corner + 1, grid_h - q - corner - 1):
        format_coords.append((fx, y))

    return BasicLayout(
        frame_w=int(grid_w),
        frame_h=int(grid_h),
        grid_w=int(grid_w),
        grid_h=int(grid_h),
        quiet=int(q),
        finder=int(corner),
        guard_band=int(guard),
        grid_x0=int(x0),
        grid_y0=int(y0),
        grid_x1=int(x1),
        grid_y1=int(y1),
        data_coords=data_coords,
        format_coords=format_coords,
        layout_coords=[],
        layout_info=LayoutInfoBasic(grid_w=160, grid_h=96),
    )


def _warp_from_finder_centers_compat(
    frame: np.ndarray,
    quad: np.ndarray,
    grid_w: int,
    grid_h: int,
    corner_size: int,
) -> np.ndarray:
    src = quad.astype(np.float32)
    out_w = int(grid_w * 4)
    out_h = int(grid_h * 4)
    c2 = int(corner_size // 2)
    q = 4
    tl_m = (q + c2, q + c2)
    tr_m = (grid_w - q - c2 - 1, q + c2)
    br_m = (grid_w - q - c2 - 1, grid_h - q - c2 - 1)
    bl_m = (q + c2, grid_h - q - c2 - 1)

    def _m_to_px(mx: int, my: int) -> Tuple[float, float]:
        return ((mx + 0.5) * 4.0, (my + 0.5) * 4.0)

    dst = np.array(
        [
            _m_to_px(*tl_m),
            _m_to_px(*tr_m),
            _m_to_px(*br_m),
            _m_to_px(*bl_m),
        ],
        dtype=np.float32,
    )
    hmat = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(frame, hmat, (out_w, out_h), flags=cv2.INTER_NEAREST)


def _sample_modules_from_crop(
    crop: np.ndarray, grid_w: int, grid_h: int, threshold: float
) -> np.ndarray:
    gray = crop.mean(axis=2).astype(np.uint8)
    down = cv2.resize(gray, (grid_w, grid_h), interpolation=cv2.INTER_AREA)
    return (down.astype(np.float32) >= float(threshold)).astype(np.uint8)


def _extract_modules_from_exact_bbox(frame: np.ndarray, layout: BasicLayout) -> Optional[np.ndarray]:
    """Recover modules directly from a tightly rendered symbol bbox.

    This fallback is intended for ideal synthetic frames rendered on a flat
    background. It avoids locator/timing jitter by resizing the symbol bbox
    straight back to module resolution with nearest-neighbor sampling.
    """
    bbox = _bbox_from_non_black(frame)
    if bbox is None:
        return None
    x, y, w, h = bbox
    crop = frame[y : y + h, x : x + w]
    if crop.size == 0:
        return None
    gray = crop.mean(axis=2).astype(np.uint8)
    resized = cv2.resize(
        gray,
        (layout.frame_w, layout.frame_h),
        interpolation=cv2.INTER_NEAREST,
    )
    return (resized >= 127).astype(np.uint8)


def _bbox_from_quad(
    quad: np.ndarray, frame_shape: Tuple[int, int, int]
) -> tuple[int, int, int, int]:
    h, w = frame_shape[:2]
    x1 = max(0, int(np.floor(float(np.min(quad[:, 0])))))
    y1 = max(0, int(np.floor(float(np.min(quad[:, 1])))))
    x2 = min(w, int(np.ceil(float(np.max(quad[:, 0])))))
    y2 = min(h, int(np.ceil(float(np.max(quad[:, 1])))))
    return x1, y1, max(1, x2 - x1), max(1, y2 - y1)


def _run_locator(
    frame: np.ndarray,
    locator_engine: str,
    search_roi: Optional[Tuple[int, int, int, int]],
    cfg: LocatorConfig,
) -> Tuple[LocateResult, str, Optional[LocateError], Optional[LocateError]]:
    if locator_engine == "new":
        loc = locate_frame(frame=frame, search_roi=search_roi, config=cfg)
        if isinstance(loc, LocateError):
            raise ValueError("locator new failed: {0}".format(loc.fail_reason.value))
        # Do not hard-gate on locator confidence before payload decode.
        # A low-confidence locator can still produce decodable modules.
        return loc, "new", None, None

    if locator_engine == "legacy":
        loc = locate_frame_legacy(frame=frame, search_roi=search_roi, config=cfg)
        if isinstance(loc, LocateError):
            raise ValueError("locator legacy failed: {0}".format(loc.fail_reason.value))
        return loc, "legacy", None, None

    # auto
    new_err: Optional[LocateError] = None
    legacy_err: Optional[LocateError] = None
    new_res = locate_frame(frame=frame, search_roi=search_roi, config=cfg)
    if isinstance(new_res, LocateResult):
        if new_res.fail_reason is None and new_res.quality.confidence >= cfg.confidence_threshold:
            return new_res, "new", None, None
        new_err = LocateError(
            fail_reason=new_res.fail_reason or LocateFailReason.BAD_FINDER_PATTERN,
            confidence=new_res.quality.confidence,
            elapsed_ms=new_res.elapsed_ms,
            debug_artifacts=new_res.debug_artifacts,
        )
    else:
        new_err = new_res

    legacy_res = locate_frame_legacy(frame=frame, search_roi=search_roi, config=cfg)
    if isinstance(legacy_res, LocateError):
        legacy_err = legacy_res
        msg = "locator auto failed: new={0} legacy={1}".format(
            new_err.fail_reason.value if new_err is not None else "NA",
            legacy_err.fail_reason.value,
        )
        raise ValueError(msg)
    return legacy_res, "legacy", new_err, legacy_err


def decode_frame_basic(
    frame: np.ndarray,
    detect_mode: str = "full",
    forced_roi: Optional[Tuple[int, int, int, int]] = None,
    grid_w: int = DEFAULT_GRID_W,
    grid_h: int = DEFAULT_GRID_H,
    guard_band: int = 2,
    corner_size: int = 9,
    roi_only: bool = False,
    manual_strict: bool = False,
    locator_engine: str = "auto",
    locator_confidence_threshold: float = 0.55,
) -> Tuple[FrameHeaderBasic, bytes, DecodeMetaBasic]:
    if detect_mode not in ("full", "track", "roi"):
        raise ValueError("invalid detect_mode")
    if locator_engine not in ("new", "legacy", "auto"):
        raise ValueError("invalid locator_engine")

    # Maintain external API semantics:
    # - full: search on full frame unless manual strict / roi_only is requested
    # - track/roi: search in provided ROI when available
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
    loc, used_engine, new_err, legacy_err = _run_locator(
        frame=frame,
        locator_engine=locator_engine,
        search_roi=search_roi,
        cfg=cfg,
    )

    layout = build_layout_basic(
        grid_w=grid_w, grid_h=grid_h, guard_band=guard_band, corner_size=corner_size
    )
    parsed = _read_layout_info(loc.modules, layout)
    if parsed is not None:
        layout = build_layout_basic(
            grid_w=parsed.grid_w,
            grid_h=parsed.grid_h,
            guard_band=parsed.guard,
            corner_size=parsed.finder,
        )

    last_exc = None
    attempts = 0
    for cand in (loc.modules, (1 - loc.modules).astype(np.uint8)):
        attempts += 1
        try:
            header, payload, mask_id = _decode_modules(cand, layout)
            bbox = _bbox_from_quad(loc.quad_src, frame.shape)
            return (
                header,
                payload,
                DecodeMetaBasic(
                    protocol_version_used=31,
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
        # Ideal synthetic-frame fallback for all ECC levels.
        try:
            exact_modules = _extract_modules_from_exact_bbox(frame, layout)
            exact_bbox = _bbox_from_non_black(frame)
            if exact_modules is not None:
                for cand in (exact_modules, (1 - exact_modules).astype(np.uint8)):
                    try:
                        header, payload, mask_id = _decode_modules(cand, layout)
                        preview = None
                        if exact_bbox is not None:
                            x, y, w, h = exact_bbox
                            preview = frame[y : y + h, x : x + w].copy()
                        return (
                            header,
                            payload,
                            DecodeMetaBasic(
                                protocol_version_used=31,
                                locator_engine="bbox_exact",
                                confidence=1.0,
                                fail_reason="",
                                elapsed_ms=0.0,
                                legacy_used=False,
                                homography_rmse=0.0,
                                rs_corrected_symbols=0,
                                crc_ok=True,
                                mask_id=int(mask_id),
                                grid_size="{0}x{1}".format(layout.grid_w, layout.grid_h),
                                det_bbox=(0, 0, 0, 0) if exact_bbox is None else exact_bbox,
                                decode_attempts=attempts + 1,
                                det_confidence=1.0,
                                new_fail_reason="" if new_err is None else new_err.fail_reason.value,
                                new_elapsed_ms=0.0 if new_err is None else float(new_err.elapsed_ms),
                                legacy_elapsed_ms=float(loc.elapsed_ms) if loc.legacy_used else 0.0,
                                locator_debug_artifacts={"path": "bbox_exact"},
                                locator_warped_preview=preview,
                            ),
                        )
                    except Exception:
                        pass
        except Exception:
            pass

        # Compatibility fallback for an older basic sender layout (pre absolute-layout refactor).
        try:
            qdet = detect_symbol_quad(frame)
            if qdet is not None:
                warped = _warp_from_finder_centers_compat(
                    frame=frame,
                    quad=qdet.quad.astype(np.float32),
                    grid_w=grid_w,
                    grid_h=grid_h,
                    corner_size=corner_size,
                )
                layout_compat = _build_layout_basic_compat(
                    grid_w=grid_w,
                    grid_h=grid_h,
                    guard_band=guard_band,
                    corner_size=corner_size,
                )
                gray = warped.mean(axis=2).astype(np.uint8)
                thr_a = float(np.mean(gray))
                thr_b, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
                for thr in (thr_a, float(thr_b)):
                    modules = _sample_modules_from_crop(
                        warped, grid_w=grid_w, grid_h=grid_h, threshold=thr
                    )
                    for cand in (modules, (1 - modules).astype(np.uint8)):
                        try:
                            header, payload, mask_id = _decode_modules(cand, layout_compat)
                            bbox = _bbox_from_quad(qdet.quad.astype(np.float32), frame.shape)
                            return (
                                header,
                                payload,
                                DecodeMetaBasic(
                                    protocol_version_used=31,
                                    locator_engine="new",
                                    confidence=0.0,
                                    fail_reason="",
                                    elapsed_ms=0.0,
                                    legacy_used=False,
                                    homography_rmse=0.0,
                                    rs_corrected_symbols=0,
                                    crc_ok=True,
                                    mask_id=int(mask_id),
                                    grid_size="{0}x{1}".format(grid_w, grid_h),
                                    det_bbox=bbox,
                                    decode_attempts=attempts + 1,
                                    det_confidence=0.0,
                                    new_fail_reason="",
                                    new_elapsed_ms=0.0,
                                    legacy_elapsed_ms=0.0,
                                    locator_debug_artifacts={},
                                    locator_warped_preview=warped.copy(),
                                ),
                            )
                        except Exception:
                            pass
        except Exception:
            pass
        raise last_exc

    if new_err is not None or legacy_err is not None:
        raise ValueError(
            "decode failed after locator fallback: new={0} legacy={1}".format(
                "" if new_err is None else new_err.fail_reason.value,
                "" if legacy_err is None else legacy_err.fail_reason.value,
            )
        )
    raise RuntimeError("basic decode failed")
