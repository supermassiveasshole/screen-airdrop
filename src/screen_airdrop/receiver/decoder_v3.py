"""V3 visual decoder: detect -> warp -> sample modules -> decode bits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np

from screen_airdrop.common.protocol_v3 import (
    V3_DEFAULT_GRID_H,
    V3_DEFAULT_GRID_W,
    V3_ECC_Q,
    V3_FINDER_SIZE,
    V3_FORMAT_SIZE,
    V3_ID_TO_ECC,
    V3_QUIET_MODULES,
    FormatInfoV3,
    FrameHeaderV3,
    decode_header_and_payload_bits,
)
from screen_airdrop.receiver.detector_v3 import detect_symbol_quad
from screen_airdrop.receiver.geometry_v3 import warp_to_grid
from screen_airdrop.sender.encoder_v3 import build_layout


@dataclass
class DecodeMetaV3:
    protocol_version_used: int
    det_confidence: float
    homography_rmse: float
    rs_corrected_symbols: int
    crc_ok: bool
    mask_id: int
    grid_size: str
    det_bbox: tuple[int, int, int, int]


def _sample_modules(warped: np.ndarray, grid_w: int, grid_h: int, cell_px: int) -> np.ndarray:
    gray = warped.mean(axis=2)
    threshold = float(np.mean(gray))
    modules = np.zeros((grid_h, grid_w), dtype=np.uint8)
    off = max(1, cell_px // 4)
    for y in range(grid_h):
        cy = y * cell_px + cell_px // 2
        for x in range(grid_w):
            cx = x * cell_px + cell_px // 2
            y1 = max(0, cy - off)
            y2 = min(gray.shape[0], cy + off + 1)
            x1 = max(0, cx - off)
            x2 = min(gray.shape[1], cx + off + 1)
            v = gray[y1:y2, x1:x2].mean()
            modules[y, x] = 1 if v >= threshold else 0
    return modules


def _sample_modules_with_threshold(
    warped: np.ndarray,
    grid_w: int,
    grid_h: int,
    cell_px: int,
    threshold: float,
) -> np.ndarray:
    gray = warped.mean(axis=2)
    modules = np.zeros((grid_h, grid_w), dtype=np.uint8)
    off = max(1, cell_px // 4)
    for y in range(grid_h):
        cy = y * cell_px + cell_px // 2
        for x in range(grid_w):
            cx = x * cell_px + cell_px // 2
            y1 = max(0, cy - off)
            y2 = min(gray.shape[0], cy + off + 1)
            x1 = max(0, cx - off)
            x2 = min(gray.shape[1], cx + off + 1)
            v = gray[y1:y2, x1:x2].mean()
            modules[y, x] = 1 if v >= threshold else 0
    return modules


def _sample_modules_from_crop(crop: np.ndarray, grid_w: int, grid_h: int) -> np.ndarray:
    gray = crop.mean(axis=2)
    h, w = gray.shape
    thr = float(np.mean(gray))
    modules = np.zeros((grid_h, grid_w), dtype=np.uint8)
    for gy in range(grid_h):
        cy = (gy + 0.5) * h / float(grid_h)
        y1 = int(max(0, cy - h / float(grid_h) * 0.25))
        y2 = int(min(h, cy + h / float(grid_h) * 0.25 + 1))
        for gx in range(grid_w):
            cx = (gx + 0.5) * w / float(grid_w)
            x1 = int(max(0, cx - w / float(grid_w) * 0.25))
            x2 = int(min(w, cx + w / float(grid_w) * 0.25 + 1))
            v = gray[y1:y2, x1:x2].mean()
            modules[gy, gx] = 1 if v >= thr else 0
    return modules


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


def _read_format_bits(modules: np.ndarray, layout) -> bytes:
    bits = [int(modules[y, x]) for x, y in layout.format_coords]
    # 3x repetition, use majority vote.
    unit_len = (V3_FORMAT_SIZE + 2) * 8
    if len(bits) < unit_len:
        raise ValueError("format area too small")
    groups = bits[: unit_len * 3]
    dec = []
    for i in range(unit_len):
        votes = 0
        for p in range(3):
            idx = p * unit_len + i
            if idx < len(groups):
                votes += groups[idx]
        dec.append(1 if votes >= 2 else 0)
    raw = bytearray()
    for i in range(0, len(dec), 8):
        b = 0
        for bit in dec[i : i + 8]:
            b = (b << 1) | (bit & 1)
        raw.append(b)
    return bytes(raw)


def _decode_from_modules(modules: np.ndarray, grid_w: int, grid_h: int) -> Tuple[FrameHeaderV3, bytes, int, str]:
    layout = build_layout(grid_w=grid_w, grid_h=grid_h)
    mask_candidates: List[int] = []
    ecc_candidates: List[str] = []
    try:
        fmt = FormatInfoV3.unpack(_read_format_bits(modules, layout))
        mask_candidates = [int(fmt.mask_id)]
        ecc_candidates = [V3_ID_TO_ECC.get(int(fmt.ecc_id), V3_ECC_Q)]
    except Exception:
        # Fast path defaults for sender-v3 defaults; fallback candidates still included.
        mask_candidates = [3, 0, 1, 2, 4, 5, 6, 7]
        ecc_candidates = [V3_ECC_Q, "H", "M", "L"]

    last_exc = None
    for mask_id in mask_candidates:
        bits: List[int] = []
        for x, y in layout.data_coords:
            v = int(modules[y, x])
            if _mask_bit(mask_id, x, y):
                v ^= 1
            bits.append(v)
        for ecc_level in ecc_candidates:
            try:
                header, payload = decode_header_and_payload_bits(bits, ecc_level=ecc_level)
                return header, payload, mask_id, ecc_level
            except Exception as exc:  # noqa: PERF203
                last_exc = exc
                continue
    if last_exc is not None:
        raise last_exc
    raise ValueError("v3 data decode failed")


def _decode_from_modules_variants(modules: np.ndarray, grid_w: int, grid_h: int) -> Tuple[FrameHeaderV3, bytes, int, str]:
    variants = [
        modules,
        np.rot90(modules, 1),
        np.rot90(modules, 2),
        np.rot90(modules, 3),
    ]
    mirrored = np.fliplr(modules)
    variants.extend(
        [
            mirrored,
            np.rot90(mirrored, 1),
            np.rot90(mirrored, 2),
            np.rot90(mirrored, 3),
        ]
    )
    last_exc = None
    for v in variants:
        if v.shape[0] != grid_h or v.shape[1] != grid_w:
            continue
        try:
            return _decode_from_modules(v, grid_w=grid_w, grid_h=grid_h)
        except Exception as exc:  # noqa: PERF203
            last_exc = exc
            continue
    if last_exc is not None:
        raise last_exc
    raise ValueError("v3 module variant decode failed")


def decode_frame_v3(
    frame: np.ndarray,
    detect_mode: str = "full",
    forced_roi: Optional[Tuple[int, int, int, int]] = None,
    grid_w: int = V3_DEFAULT_GRID_W,
    grid_h: int = V3_DEFAULT_GRID_H,
) -> Tuple[FrameHeaderV3, bytes, DecodeMetaV3]:
    view = frame
    if detect_mode == "roi" and forced_roi is not None:
        x, y, w, h = forced_roi
        x = max(0, int(x))
        y = max(0, int(y))
        w = max(1, int(w))
        h = max(1, int(h))
        view = frame[y : y + h, x : x + w]

    candidates = []
    det = detect_symbol_quad(view)
    if det is not None:
        centers = det.quad.astype(np.float32)
        c = float(V3_QUIET_MODULES + (V3_FINDER_SIZE // 2))
        dx_mod = float(grid_w - 2 * int(c) - 1)
        dy_mod = float(grid_h - 2 * int(c) - 1)
        ux = (centers[1] - centers[0]) / max(1e-6, dx_mod)
        uy = (centers[3] - centers[0]) / max(1e-6, dy_mod)
        outer_quad = np.array(
            [
                centers[0] - c * ux - c * uy,
                centers[1] + c * ux - c * uy,
                centers[2] + c * ux + c * uy,
                centers[3] - c * ux + c * uy,
            ],
            dtype=np.float32,
        )
        candidates.append(("quad", outer_quad, float(det.confidence)))

    gray = view.mean(axis=2).astype(np.uint8)
    mask = (gray > 8).astype(np.uint8)
    nlabels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if nlabels > 1:
        best = None
        best_area = -1
        for i in range(1, nlabels):
            x = int(stats[i, cv2.CC_STAT_LEFT])
            y = int(stats[i, cv2.CC_STAT_TOP])
            w = int(stats[i, cv2.CC_STAT_WIDTH])
            h = int(stats[i, cv2.CC_STAT_HEIGHT])
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area > best_area and w > 20 and h > 20:
                best_area = area
                best = (x, y, w, h)
        if best is not None:
            bx, by, bw, bh = best
            candidates.append(("bbox", (bx, by, bw, bh), 0.35))

    if not candidates:
        raise ValueError("v3 finder detect failed")
    # Prefer axis-aligned bbox path first for resize/window-move scenes.
    candidates.sort(key=lambda t: 0 if t[0] == "bbox" else 1)
    cell_px = 8
    last_exc = None
    for mode, geo, conf in candidates:
        if mode == "bbox":
            bx, by, bw, bh = geo
            crop = view[by : by + bh, bx : bx + bw]
            direct_modules = _sample_modules_from_crop(crop, grid_w=grid_w, grid_h=grid_h)
            try:
                header, payload, mask_id, _ = _decode_from_modules_variants(direct_modules, grid_w=grid_w, grid_h=grid_h)
                return header, payload, DecodeMetaV3(
                    protocol_version_used=3,
                    det_confidence=float(conf),
                    homography_rmse=0.0,
                    rs_corrected_symbols=0,
                    crc_ok=True,
                    mask_id=mask_id,
                    grid_size="{0}x{1}".format(grid_w, grid_h),
                    det_bbox=(int(bx), int(by), int(bw), int(bh)),
                )
            except Exception as exc:  # noqa: PERF203
                last_exc = exc
                warped = cv2.resize(crop, (grid_w * cell_px, grid_h * cell_px), interpolation=cv2.INTER_NEAREST)
        else:
            warped, _ = warp_to_grid(view, geo, grid_w=grid_w, grid_h=grid_h, cell_px=cell_px)
        g = warped.mean(axis=2).astype(np.uint8)
        otsu_thr, _ = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        q45 = float(np.percentile(g, 45))
        q50 = float(np.percentile(g, 50))
        q55 = float(np.percentile(g, 55))
        thr_candidates = [
            127.0,
            float(np.mean(g)),
            float(otsu_thr),
            q50,
            q45,
            q55,
        ]
        for thr in thr_candidates:
            try:
                modules = _sample_modules_with_threshold(warped, grid_w=grid_w, grid_h=grid_h, cell_px=cell_px, threshold=thr)
                for cand_modules in (modules, (1 - modules).astype(np.uint8)):
                    try:
                        header, payload, mask_id, _ = _decode_from_modules_variants(
                            cand_modules, grid_w=grid_w, grid_h=grid_h
                        )
                        return header, payload, DecodeMetaV3(
                            protocol_version_used=3,
                            det_confidence=float(conf),
                            homography_rmse=0.0,
                            rs_corrected_symbols=0,
                            crc_ok=True,
                            mask_id=mask_id,
                            grid_size="{0}x{1}".format(grid_w, grid_h),
                            det_bbox=(
                                int(np.min(geo[:, 0])) if mode == "quad" else int(bx),
                                int(np.min(geo[:, 1])) if mode == "quad" else int(by),
                                int(np.max(geo[:, 0]) - np.min(geo[:, 0])) if mode == "quad" else int(bw),
                                int(np.max(geo[:, 1]) - np.min(geo[:, 1])) if mode == "quad" else int(bh),
                            ),
                        )
                    except Exception as exc:  # noqa: PERF203
                        last_exc = exc
                        continue
            except Exception as exc:  # noqa: PERF203
                last_exc = exc
                continue
    if last_exc is not None:
        raise last_exc
    raise ValueError("v3 decode failed")
