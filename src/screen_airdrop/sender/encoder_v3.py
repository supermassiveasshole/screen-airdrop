"""V3 visual encoder: module-grid symbol with QR-style locators."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Set, Tuple

import cv2
import numpy as np

from screen_airdrop.common.protocol_v3 import (
    V3_ALIGNMENT_SIZE,
    V3_DEFAULT_GRID_H,
    V3_DEFAULT_GRID_W,
    V3_ECC_LEVELS,
    V3_ECC_Q,
    V3_ECC_TO_ID,
    V3_FINDER_SIZE,
    V3_FORMAT_MAGIC,
    V3_QUIET_MODULES,
    V3_TIMING_OFFSET,
    FormatInfoV3,
    FrameHeaderV3,
    encode_header_and_payload_bits,
)


@dataclass
class V3Layout:
    grid_w: int
    grid_h: int
    reserved: Set[Tuple[int, int]]
    data_coords: List[Tuple[int, int]]
    format_coords: List[Tuple[int, int]]
    finder_centers: List[Tuple[int, int]]


def _draw_finder(mat: np.ndarray, left: int, top: int, size: int = V3_FINDER_SIZE) -> None:
    # white outer, black ring, white ring, black center
    mat[top : top + size, left : left + size] = 1
    mat[top + 1 : top + size - 1, left + 1 : left + size - 1] = 0
    mat[top + 2 : top + size - 2, left + 2 : left + size - 2] = 1
    mat[top + 3 : top + size - 3, left + 3 : left + size - 3] = 0


def _draw_alignment(mat: np.ndarray, cx: int, cy: int, size: int = V3_ALIGNMENT_SIZE) -> None:
    r = size // 2
    x1, y1 = cx - r, cy - r
    x2, y2 = cx + r + 1, cy + r + 1
    mat[y1:y2, x1:x2] = 1
    mat[y1 + 1 : y2 - 1, x1 + 1 : x2 - 1] = 0
    mat[cy, cx] = 1


def _reserve_rect(reserved: Set[Tuple[int, int]], x: int, y: int, w: int, h: int) -> None:
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            reserved.add((xx, yy))


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


def _score_mask(mat: np.ndarray) -> int:
    # low-complexity penalty inspired by QR mask score.
    h, w = mat.shape
    penalty = 0
    for y in range(h):
        run = 1
        for x in range(1, w):
            if mat[y, x] == mat[y, x - 1]:
                run += 1
            else:
                if run >= 5:
                    penalty += run - 2
                run = 1
        if run >= 5:
            penalty += run - 2
    for x in range(w):
        run = 1
        for y in range(1, h):
            if mat[y, x] == mat[y - 1, x]:
                run += 1
            else:
                if run >= 5:
                    penalty += run - 2
                run = 1
        if run >= 5:
            penalty += run - 2
    return int(penalty)


def build_layout(grid_w: int = V3_DEFAULT_GRID_W, grid_h: int = V3_DEFAULT_GRID_H) -> V3Layout:
    reserved: Set[Tuple[int, int]] = set()
    q = V3_QUIET_MODULES
    fs = V3_FINDER_SIZE

    finder_tl = (q + fs // 2, q + fs // 2)
    finder_tr = (grid_w - q - fs // 2 - 1, q + fs // 2)
    finder_bl = (q + fs // 2, grid_h - q - fs // 2 - 1)
    finder_br = (grid_w - q - fs // 2 - 1, grid_h - q - fs // 2 - 1)
    finders = [finder_tl, finder_tr, finder_bl, finder_br]

    for cx, cy in finders:
        _reserve_rect(reserved, cx - fs // 2 - 1, cy - fs // 2 - 1, fs + 2, fs + 2)

    # alignment marks
    ax = [grid_w // 3, (2 * grid_w) // 3]
    ay = [grid_h // 3, (2 * grid_h) // 3]
    for cy in ay:
        for cx in ax:
            _reserve_rect(
                reserved,
                cx - V3_ALIGNMENT_SIZE // 2 - 1,
                cy - V3_ALIGNMENT_SIZE // 2 - 1,
                V3_ALIGNMENT_SIZE + 2,
                V3_ALIGNMENT_SIZE + 2,
            )

    # timing lines
    for x in range(q, grid_w - q):
        reserved.add((x, V3_TIMING_OFFSET))
    for y in range(q, grid_h - q):
        reserved.add((V3_TIMING_OFFSET, y))

    # format area: long strips for repeated format payload.
    format_coords: List[Tuple[int, int]] = []
    for x in range(q, grid_w - q):
        c = (x, q - 1)
        reserved.add(c)
        format_coords.append(c)
    for y in range(q, grid_h - q):
        c = (q - 1, y)
        reserved.add(c)
        format_coords.append(c)

    data_coords: List[Tuple[int, int]] = []
    for y in range(q, grid_h - q):
        for x in range(q, grid_w - q):
            if (x, y) in reserved:
                continue
            data_coords.append((x, y))

    return V3Layout(
        grid_w=grid_w,
        grid_h=grid_h,
        reserved=reserved,
        data_coords=data_coords,
        format_coords=format_coords,
        finder_centers=finders,
    )


def _paint_structures(mat: np.ndarray, layout: V3Layout) -> None:
    q = V3_QUIET_MODULES
    fs = V3_FINDER_SIZE
    # quiet zone
    mat[:q, :] = 1
    mat[-q:, :] = 1
    mat[:, :q] = 1
    mat[:, -q:] = 1

    # finders
    for cx, cy in layout.finder_centers:
        _draw_finder(mat, cx - fs // 2, cy - fs // 2, fs)

    # alignment
    ax = [layout.grid_w // 3, (2 * layout.grid_w) // 3]
    ay = [layout.grid_h // 3, (2 * layout.grid_h) // 3]
    for cy in ay:
        for cx in ax:
            _draw_alignment(mat, cx, cy)

    # timing patterns
    for x in range(q, layout.grid_w - q):
        mat[V3_TIMING_OFFSET, x] = 1 if (x % 2 == 0) else 0
    for y in range(q, layout.grid_h - q):
        mat[y, V3_TIMING_OFFSET] = 1 if (y % 2 == 0) else 0


def _write_format(mat: np.ndarray, layout: V3Layout, frame_type: int, mask_id: int, ecc_level: str) -> None:
    fmt = FormatInfoV3(
        magic=V3_FORMAT_MAGIC,
        version=3,
        frame_type=frame_type,
        mask_id=mask_id,
        ecc_id=V3_ECC_TO_ID[ecc_level],
        reserved=0,
    )
    bits = []
    raw = fmt.pack()
    for b in raw:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)
    rep = 3
    stream = bits * rep
    for idx, c in enumerate(layout.format_coords):
        if idx >= len(stream):
            break
        x, y = c
        mat[y, x] = stream[idx]


def _render_modules_to_frame(
    modules: np.ndarray,
    width: int,
    height: int,
    outer_padding_px: int = 0,
    outer_padding_white: bool = False,
) -> np.ndarray:
    mh, mw = modules.shape
    pad = max(0, int(outer_padding_px))
    avail_w = max(1, width - 2 * pad)
    avail_h = max(1, height - 2 * pad)
    scale = max(1, min(avail_w // mw, avail_h // mh))
    sym_w = mw * scale
    sym_h = mh * scale
    symbol = cv2.resize((modules * 255).astype(np.uint8), (sym_w, sym_h), interpolation=cv2.INTER_NEAREST)
    frame = np.full((height, width), 255 if outer_padding_white else 0, dtype=np.uint8)
    ox = pad + (avail_w - sym_w) // 2
    oy = pad + (avail_h - sym_h) // 2
    frame[oy : oy + sym_h, ox : ox + sym_w] = symbol
    return np.dstack([frame, frame, frame])


def frame_capacity_bytes(
    grid_w: int,
    grid_h: int,
    ecc_level: str = V3_ECC_Q,
) -> int:
    layout = build_layout(grid_w=grid_w, grid_h=grid_h)
    rep = 3 if ecc_level not in V3_ECC_LEVELS else {"L": 1, "M": 2, "Q": 3, "H": 4}[ecc_level]
    usable_bits = max(0, len(layout.data_coords) - (len(FormatInfoV3(0, 0, 0, 0, 0).pack()) * 8))
    raw_bits = usable_bits // rep
    return max(0, raw_bits // 8)


def encode_frame_v3(
    header: FrameHeaderV3,
    payload: bytes,
    width: int,
    height: int,
    grid_w: int = V3_DEFAULT_GRID_W,
    grid_h: int = V3_DEFAULT_GRID_H,
    ecc_level: str = V3_ECC_Q,
    forced_mask: int | None = 3,
    outer_padding_px: int = 0,
    outer_padding_white: bool = False,
) -> np.ndarray:
    modules = build_symbol_modules_v3(
        header=header,
        payload=payload,
        grid_w=grid_w,
        grid_h=grid_h,
        ecc_level=ecc_level,
        forced_mask=forced_mask,
    )
    return _render_modules_to_frame(
        modules,
        width=width,
        height=height,
        outer_padding_px=outer_padding_px,
        outer_padding_white=outer_padding_white,
    )


def build_symbol_modules_v3(
    header: FrameHeaderV3,
    payload: bytes,
    grid_w: int = V3_DEFAULT_GRID_W,
    grid_h: int = V3_DEFAULT_GRID_H,
    ecc_level: str = V3_ECC_Q,
    forced_mask: int | None = 3,
) -> np.ndarray:
    layout = build_layout(grid_w=grid_w, grid_h=grid_h)
    base = np.zeros((grid_h, grid_w), dtype=np.uint8)
    _paint_structures(base, layout)

    bits = encode_header_and_payload_bits(header, payload, ecc_level=ecc_level)
    bits = bits[: len(layout.data_coords)]
    if len(bits) < len(layout.data_coords):
        bits.extend([0] * (len(layout.data_coords) - len(bits)))

    candidates = [forced_mask] if forced_mask is not None else list(range(8))
    best_mat = None
    best_mask = 0
    best_score = None
    for mask_id in candidates:
        m = base.copy()
        for i, (x, y) in enumerate(layout.data_coords):
            v = bits[i]
            if _mask_bit(mask_id, x, y):
                v ^= 1
            m[y, x] = v
        _write_format(m, layout, frame_type=header.frame_type, mask_id=mask_id, ecc_level=ecc_level)
        score = _score_mask(m)
        if best_score is None or score < best_score:
            best_score = score
            best_mat = m
            best_mask = mask_id
    assert best_mat is not None
    _write_format(best_mat, layout, frame_type=header.frame_type, mask_id=best_mask, ecc_level=ecc_level)
    return best_mat
