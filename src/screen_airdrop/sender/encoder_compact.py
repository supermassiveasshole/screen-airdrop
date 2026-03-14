"""Compact visual encoder with reduced layout overhead."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import cv2
import numpy as np

from screen_airdrop.common.layout_compact import (
    DEFAULT_FINDER_COMPACT,
    DEFAULT_GRID_H_COMPACT,
    DEFAULT_GRID_W_COMPACT,
    DEFAULT_GUARD_COMPACT,
    DEFAULT_QUIET_COMPACT,
    FLAG_TIMING_ENABLED,
    LayoutInfoCompact,
)
from screen_airdrop.common.protocol_basic import (
    ECC_LEVELS,
    ECC_Q,
    ECC_TO_ID,
    FORMAT_MAGIC,
    HEADER_SIZE,
    FormatInfoBasic,
    FrameHeaderBasic,
    encode_header_and_payload_bits,
)


@dataclass
class CompactLayout:
    frame_w: int
    frame_h: int
    grid_w: int
    grid_h: int
    quiet: int
    finder: int
    guard_band: int
    grid_x0: int
    grid_y0: int
    grid_x1: int
    grid_y1: int
    data_coords: List[Tuple[int, int]]
    format_coords: List[Tuple[int, int]]
    layout_coords: List[Tuple[int, int]]
    layout_info: LayoutInfoCompact


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


def build_layout_compact(
    grid_w: int = DEFAULT_GRID_W_COMPACT,
    grid_h: int = DEFAULT_GRID_H_COMPACT,
    guard_band: int = DEFAULT_GUARD_COMPACT,
    corner_size: int = DEFAULT_FINDER_COMPACT,
) -> CompactLayout:
    """Build compact protocol layout with reduced overhead."""
    q = int(DEFAULT_QUIET_COMPACT)
    f = max(7, int(corner_size))
    if f % 2 == 0:
        f += 1
    guard = max(1, int(guard_band))
    gx = int(grid_w)
    gy = int(grid_h)

    info = LayoutInfoCompact(
        quiet=q,
        finder=f,
        guard=guard,
        grid_w=gx,
        grid_h=gy,
        flags=FLAG_TIMING_ENABLED,
    )
    info.validate()

    fw = info.frame_w
    fh = info.frame_h
    x0 = q + f + guard
    y0 = q + f + guard
    x1 = x0 + gx - 1
    y1 = y0 + gy - 1

    data_coords = []
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            data_coords.append((x, y))

    format_coords: List[Tuple[int, int]] = []
    fy = q + (f // 2)
    fx = q + (f // 2)
    for x in range(q + f, fw - q - f):
        format_coords.append((x, fy))
    for y in range(q + f, fh - q - f):
        format_coords.append((fx, y))

    layout_coords: List[Tuple[int, int]] = []
    ly = fh - q - (f // 2) - 1
    lx = fw - q - (f // 2) - 1
    for x in range(q + f, fw - q - f):
        layout_coords.append((x, ly))
    for y in range(q + f, fh - q - f):
        layout_coords.append((lx, y))

    return CompactLayout(
        frame_w=fw,
        frame_h=fh,
        grid_w=gx,
        grid_h=gy,
        quiet=q,
        finder=f,
        guard_band=guard,
        grid_x0=x0,
        grid_y0=y0,
        grid_x1=x1,
        grid_y1=y1,
        data_coords=data_coords,
        format_coords=format_coords,
        layout_coords=layout_coords,
        layout_info=info,
    )


def _draw_finder_compact(mat: np.ndarray, left: int, top: int, size: int) -> None:
    """Draw 7x7 compact finder with 2 concentric layers.

    For size=7:
    - Layer 1 (outer): all black (7x7)
    - Layer 2 (middle): white ring (5x5, leaving 1 module border)
    - Layer 3 (inner): black center (3x3, leaving 2 module border)
    """
    # Layer 1: outer black square
    mat[top : top + size, left : left + size] = 1

    # Layer 2: white ring
    mat[top + 1 : top + size - 1, left + 1 : left + size - 1] = 0

    # Layer 3: black center
    mat[top + 2 : top + size - 2, left + 2 : left + size - 2] = 1


def _paint_static_layers(mat: np.ndarray, layout: CompactLayout) -> None:
    """Paint quiet zones, finders, and timing rails."""
    q = layout.quiet
    f = layout.finder
    h, w = mat.shape

    # Quiet zones (white borders)
    mat[:q, :] = 1
    mat[h - q :, :] = 1
    mat[:, :q] = 1
    mat[:, w - q :] = 1

    # Four corner finders
    _draw_finder_compact(mat, q, q, f)
    _draw_finder_compact(mat, w - q - f, q, f)
    _draw_finder_compact(mat, q, h - q - f, f)
    _draw_finder_compact(mat, w - q - f, h - q - f, f)

    # Row/col timing rails around the data grid
    tx0 = layout.grid_x0 - 1
    tx1 = layout.grid_x1 + 1
    ty0 = layout.grid_y0 - 1
    ty1 = layout.grid_y1 + 1
    for x in range(tx0, tx1 + 1):
        mat[ty0, x] = 1 if x % 2 == 0 else 0
        mat[ty1, x] = 1 if x % 2 == 0 else 0
    for y in range(ty0, ty1 + 1):
        mat[y, tx0] = 1 if y % 2 == 0 else 0
        mat[y, tx1] = 1 if y % 2 == 0 else 0


def _write_format(
    mat: np.ndarray, layout: CompactLayout, frame_type: int, mask_id: int, ecc_level: str
) -> None:
    """Write format information (reused from basic)."""
    reserved = ((layout.guard_band & 0xFF) << 8) | (layout.finder & 0xFF)
    fmt = FormatInfoBasic(
        magic=FORMAT_MAGIC,
        version=31,  # Keep version for compatibility
        frame_type=frame_type,
        mask_id=mask_id,
        ecc_id=ECC_TO_ID[ecc_level],
        reserved=reserved,
    )
    bits = []
    for b in fmt.pack():
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)
    repeated = bits * 3
    for i, (x, y) in enumerate(layout.format_coords):
        if i >= len(repeated):
            break
        mat[y, x] = repeated[i]


def _write_layout_info(mat: np.ndarray, layout: CompactLayout) -> None:
    """Write layout information to sync frames."""
    bits = []
    for b in layout.layout_info.pack():
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)
    repeated = bits * 2
    for i, (x, y) in enumerate(layout.layout_coords):
        if i >= len(repeated):
            break
        mat[y, x] = repeated[i]


def _render_modules(
    modules: np.ndarray,
    width: int,
    height: int,
    outer_padding_px: int = 0,
    outer_padding_white: bool = False,
) -> np.ndarray:
    """Render module matrix to BGR image (reused from basic)."""
    mh, mw = modules.shape
    pad = max(0, int(outer_padding_px))
    avail_w = max(1, width - 2 * pad)
    avail_h = max(1, height - 2 * pad)
    scale = max(1, min(avail_w // mw, avail_h // mh))
    sym_w = mw * scale
    sym_h = mh * scale
    symbol = cv2.resize(
        (modules * 255).astype(np.uint8), (sym_w, sym_h), interpolation=cv2.INTER_NEAREST
    )
    frame = np.full((height, width), 255 if outer_padding_white else 0, dtype=np.uint8)
    ox = pad + (avail_w - sym_w) // 2
    oy = pad + (avail_h - sym_h) // 2
    frame[oy : oy + sym_h, ox : ox + sym_w] = symbol
    return np.dstack([frame, frame, frame])


def frame_capacity_bytes_compact(
    grid_w: int = DEFAULT_GRID_W_COMPACT,
    grid_h: int = DEFAULT_GRID_H_COMPACT,
    ecc_level: str = ECC_Q,
    guard_band: int = DEFAULT_GUARD_COMPACT,
    corner_size: int = DEFAULT_FINDER_COMPACT,
) -> int:
    """Calculate frame payload capacity in bytes."""
    if ecc_level not in ECC_LEVELS:
        raise ValueError("invalid ecc level")
    layout = build_layout_compact(
        grid_w=grid_w, grid_h=grid_h, guard_band=guard_band, corner_size=corner_size
    )
    rep = {"L": 1, "M": 2, "Q": 3, "H": 4}[ecc_level]
    total_raw_bytes = (len(layout.data_coords) // rep) // 8
    return max(0, total_raw_bytes - HEADER_SIZE - 2)


def build_symbol_modules_compact(
    header: FrameHeaderBasic,
    payload: bytes,
    grid_w: int = DEFAULT_GRID_W_COMPACT,
    grid_h: int = DEFAULT_GRID_H_COMPACT,
    ecc_level: str = ECC_Q,
    guard_band: int = DEFAULT_GUARD_COMPACT,
    corner_size: int = DEFAULT_FINDER_COMPACT,
    forced_mask: int = 3,
) -> np.ndarray:
    """Build compact protocol symbol module matrix."""
    layout = build_layout_compact(
        grid_w=grid_w, grid_h=grid_h, guard_band=guard_band, corner_size=corner_size
    )
    mat = np.zeros((layout.frame_h, layout.frame_w), dtype=np.uint8)
    _paint_static_layers(mat, layout)

    bits = encode_header_and_payload_bits(header, payload, ecc_level=ecc_level)
    if len(bits) < len(layout.data_coords):
        bits.extend([0] * (len(layout.data_coords) - len(bits)))
    else:
        bits = bits[: len(layout.data_coords)]

    mask_id = int(forced_mask) & 7
    for i, (x, y) in enumerate(layout.data_coords):
        v = bits[i]
        if _mask_bit(mask_id, x, y):
            v ^= 1
        mat[y, x] = v

    _write_format(mat, layout, frame_type=header.frame_type, mask_id=mask_id, ecc_level=ecc_level)
    _write_layout_info(mat, layout)
    return mat


def encode_frame_compact(
    header: FrameHeaderBasic,
    payload: bytes,
    width: int,
    height: int,
    grid_w: int = DEFAULT_GRID_W_COMPACT,
    grid_h: int = DEFAULT_GRID_H_COMPACT,
    ecc_level: str = ECC_Q,
    guard_band: int = DEFAULT_GUARD_COMPACT,
    corner_size: int = DEFAULT_FINDER_COMPACT,
    forced_mask: int = 3,
    outer_padding_px: int = 0,
    outer_padding_white: bool = False,
) -> np.ndarray:
    """Encode frame using compact protocol."""
    modules = build_symbol_modules_compact(
        header=header,
        payload=payload,
        grid_w=grid_w,
        grid_h=grid_h,
        ecc_level=ecc_level,
        guard_band=guard_band,
        corner_size=corner_size,
        forced_mask=forced_mask,
    )
    return _render_modules(
        modules,
        width=width,
        height=height,
        outer_padding_px=outer_padding_px,
        outer_padding_white=outer_padding_white,
    )
