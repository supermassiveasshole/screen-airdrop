"""Gray4 visual encoder with compact geometry and 4-level payload modulation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

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
    ECC_TO_REP,
    FORMAT_MAGIC,
    HEADER_SIZE,
    FormatInfoBasic,
    FrameHeaderBasic,
)
from screen_airdrop.common.protocol_gray4 import (
    ecc_repetition_symbols,
    encode_gray4_symbols,
)

GRAY4_HEADER_REP_BONUS = 0
GRAY4_MAX_HEADER_REP = 4


def _bits_from_bytes(data: bytes) -> List[int]:
    bits: List[int] = []
    for b in data:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)
    return bits


@dataclass
class Gray4Layout:
    """Layout structure for gray4 protocol (reuses compact geometry)."""
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
    data_capacity_symbols: int  # Number of 2-bit symbols available


def _mask_bit(mask_id: int, x: int, y: int) -> int:
    """Mask pattern (reused from basic protocol)."""
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


def gray4_header_repetition(payload_rep: int) -> int:
    """Header uses slightly stronger repetition than payload within the same frame."""
    return max(1, min(GRAY4_MAX_HEADER_REP, int(payload_rep) + GRAY4_HEADER_REP_BONUS))


def build_layout_gray4(
    grid_w: int = DEFAULT_GRID_W_COMPACT,
    grid_h: int = DEFAULT_GRID_H_COMPACT,
    guard_band: int = DEFAULT_GUARD_COMPACT,
    corner_size: int = DEFAULT_FINDER_COMPACT,
) -> Gray4Layout:
    """Build layout for gray4 protocol on top of compact geometry."""
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

    # Calculate symbol capacity (2 bits per module)
    data_capacity_symbols = len(data_coords)

    return Gray4Layout(
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
        data_capacity_symbols=data_capacity_symbols,
    )


def _draw_finder(mat: np.ndarray, left: int, top: int, size: int) -> None:
    """Draw compact-compatible 7x7 finder using module values 0/3."""
    mat[top : top + size, left : left + size] = 3
    mat[top + 1 : top + size - 1, left + 1 : left + size - 1] = 0
    mat[top + 2 : top + size - 2, left + 2 : left + size - 2] = 3
    if size >= 9:
        mat[top + 3 : top + size - 3, left + 3 : left + size - 3] = 0


def _paint_static_layers(mat: np.ndarray, layout: Gray4Layout) -> None:
    """Paint binary static layers (quiet zones, finders, timing rails)."""
    q = layout.quiet
    f = layout.finder
    h, w = mat.shape

    mat[:q, :] = 3
    mat[h - q :, :] = 3
    mat[:, :q] = 3
    mat[:, w - q :] = 3

    # Finder patterns (binary)
    _draw_finder(mat, q, q, f)
    _draw_finder(mat, w - q - f, q, f)
    _draw_finder(mat, q, h - q - f, f)
    _draw_finder(mat, w - q - f, h - q - f, f)

    tx0 = layout.grid_x0 - 1
    tx1 = layout.grid_x1 + 1
    ty0 = layout.grid_y0 - 1
    ty1 = layout.grid_y1 + 1
    for x in range(tx0, tx1 + 1):
        mat[ty0, x] = 3 if x % 2 == 0 else 0
        mat[ty1, x] = 3 if x % 2 == 0 else 0
    for y in range(ty0, ty1 + 1):
        mat[y, tx0] = 3 if y % 2 == 0 else 0
        mat[y, tx1] = 3 if y % 2 == 0 else 0


def _write_format(
    mat: np.ndarray, layout: Gray4Layout, frame_type: int, mask_id: int, ecc_level: str
) -> None:
    """Write binary format info with adaptive repetition."""
    reserved = ((layout.guard_band & 0xFF) << 8) | (layout.finder & 0xFF)
    fmt = FormatInfoBasic(
        magic=FORMAT_MAGIC,
        version=31,
        frame_type=frame_type,
        mask_id=mask_id,
        ecc_id=ECC_TO_ID[ecc_level],
        reserved=reserved,
    )
    bits = []
    for b in fmt.pack():
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)

    # Determine repetition level based on available coordinates
    unit_len = len(bits)
    available_coords = len(layout.format_coords)

    if available_coords >= unit_len * 3:
        # Full 3x repetition
        rep = 3
    elif available_coords >= unit_len * 2:
        # 2x repetition
        rep = 2
    else:
        # No repetition
        rep = 1

    repeated = bits * rep
    for i, (x, y) in enumerate(layout.format_coords):
        if i >= len(repeated):
            break
        mat[y, x] = 3 if repeated[i] else 0


def _write_layout_info(mat: np.ndarray, layout: Gray4Layout) -> None:
    """Write binary layout info with adaptive repetition."""
    bits = []
    for b in layout.layout_info.pack():
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)

    # Determine repetition level based on available coordinates
    unit_len = len(bits)
    available_coords = len(layout.layout_coords)

    if available_coords >= unit_len * 2:
        # Full 2x repetition
        rep = 2
    else:
        # No repetition
        rep = 1

    repeated = bits * rep
    for i, (x, y) in enumerate(layout.layout_coords):
        if i >= len(repeated):
            break
        mat[y, x] = 3 if repeated[i] else 0


def _paint_sync_calibration_payload(
    mat: np.ndarray,
    layout: Gray4Layout,
    header_cells: int,
    mask_id: int,
) -> None:
    payload_coords = layout.data_coords[header_cells:]
    if not payload_coords:
        return
    x_mid = 0.5 * float(layout.grid_x0 + layout.grid_x1)
    y_mid = 0.5 * float(layout.grid_y0 + layout.grid_y1)
    for x, y in payload_coords:
        if y <= y_mid:
            target = 0 if x <= x_mid else 1
        else:
            target = 2 if x <= x_mid else 3
        sym = target ^ 0x03 if _mask_bit(mask_id, x, y) else target
        mat[y, x] = sym & 0x03


def _render_modules_gray4(
    modules: np.ndarray,
    width: int,
    height: int,
    outer_padding_px: int = 0,
    outer_padding_white: bool = False,
) -> np.ndarray:
    """
    Render gray4 module matrix to RGB image.
    
    Modules contain values 0-3 and are mapped directly to grayscale levels.
    """
    mh, mw = modules.shape
    pad = max(0, int(outer_padding_px))
    avail_w = max(1, width - 2 * pad)
    avail_h = max(1, height - 2 * pad)
    scale = max(1, min(avail_w // mw, avail_h // mh))
    sym_w = mw * scale
    sym_h = mh * scale

    lut = np.array([0, 85, 170, 255], dtype=np.uint8)
    gray_image = lut[modules]
    symbol = np.repeat(np.repeat(gray_image, scale, axis=0), scale, axis=1)

    frame = np.full((height, width), 255 if outer_padding_white else 0, dtype=np.uint8)
    ox = pad + (avail_w - sym_w) // 2
    oy = pad + (avail_h - sym_h) // 2
    frame[oy : oy + sym_h, ox : ox + sym_w] = symbol
    return np.dstack([frame, frame, frame])


def frame_capacity_bytes_gray4(
    grid_w: int = DEFAULT_GRID_W_COMPACT,
    grid_h: int = DEFAULT_GRID_H_COMPACT,
    ecc_level: str = ECC_Q,
    guard_band: int = DEFAULT_GUARD_COMPACT,
    corner_size: int = DEFAULT_FINDER_COMPACT,
) -> int:
    """Calculate payload capacity in bytes for gray4 protocol."""
    if ecc_level not in ECC_LEVELS:
        raise ValueError("invalid ecc level")
    layout = build_layout_gray4(
        grid_w=grid_w, grid_h=grid_h, guard_band=guard_band, corner_size=corner_size
    )
    rep = ECC_TO_REP[ecc_level]
    header_rep = gray4_header_repetition(rep)
    header_cells = HEADER_SIZE * 8 * header_rep
    payload_cells = max(0, layout.data_capacity_symbols - header_cells)
    total_raw_bytes = (payload_cells // rep) // 4
    return max(0, total_raw_bytes - 2)


def build_symbol_modules_gray4(
    header: FrameHeaderBasic,
    payload: bytes,
    grid_w: int = DEFAULT_GRID_W_COMPACT,
    grid_h: int = DEFAULT_GRID_H_COMPACT,
    ecc_level: str = ECC_Q,
    guard_band: int = DEFAULT_GUARD_COMPACT,
    corner_size: int = DEFAULT_FINDER_COMPACT,
    forced_mask: int = 3,
) -> np.ndarray:
    """
    Build gray4 module matrix with 4-level symbols (0-3).
    
    Static regions use 0/3 so they stay binary after grayscale rendering.
    """
    layout = build_layout_gray4(
        grid_w=grid_w, grid_h=grid_h, guard_band=guard_band, corner_size=corner_size
    )
    mat = np.zeros((layout.frame_h, layout.frame_w), dtype=np.uint8)
    
    # Paint binary static layers (finders, timing, quiet zones)
    _paint_static_layers(mat, layout)
    
    # Encode header + payload as gray4 symbols
    rep = ECC_TO_REP[ecc_level]
    header_rep = gray4_header_repetition(rep)
    mask_id = int(forced_mask) & 7

    header_bits = _bits_from_bytes(header.pack())
    header_bits_with_ecc: List[int] = []
    for bit in header_bits:
        for _ in range(header_rep):
            header_bits_with_ecc.append(bit)

    header_cells = len(header_bits_with_ecc)
    if header_cells > len(layout.data_coords):
        raise ValueError("gray4 layout too small for header")

    for i, (x, y) in enumerate(layout.data_coords[:header_cells]):
        bit = int(header_bits_with_ecc[i]) & 0x01
        if _mask_bit(mask_id, x, y):
            bit ^= 1
        mat[y, x] = 3 if bit else 0

    if int(header.frame_type) == 0:
        _paint_sync_calibration_payload(mat, layout, header_cells, mask_id)
        _write_format(mat, layout, frame_type=header.frame_type, mask_id=mask_id, ecc_level=ecc_level)
        _write_layout_info(mat, layout)
        return mat

    payload_coords = layout.data_coords[header_cells:]
    capacity_symbols = (len(payload_coords) // rep)
    symbols = encode_gray4_symbols(payload, capacity_symbols)
    symbols_with_ecc = ecc_repetition_symbols(symbols, rep)
    if len(symbols_with_ecc) < len(payload_coords):
        symbols_with_ecc.extend([0] * (len(payload_coords) - len(symbols_with_ecc)))
    else:
        symbols_with_ecc = symbols_with_ecc[: len(payload_coords)]

    for i, (x, y) in enumerate(payload_coords):
        sym = symbols_with_ecc[i] & 0x03
        if _mask_bit(mask_id, x, y):
            sym ^= 0x03
        mat[y, x] = sym
    
    # Write binary format and layout info
    _write_format(mat, layout, frame_type=header.frame_type, mask_id=mask_id, ecc_level=ecc_level)
    _write_layout_info(mat, layout)
    
    return mat


def encode_frame_gray4(
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
    """Encode a gray4 frame with 4-level grayscale modulation."""
    modules = build_symbol_modules_gray4(
        header=header,
        payload=payload,
        grid_w=grid_w,
        grid_h=grid_h,
        ecc_level=ecc_level,
        guard_band=guard_band,
        corner_size=corner_size,
        forced_mask=forced_mask,
    )
    return _render_modules_gray4(
        modules,
        width=width,
        height=height,
        outer_padding_px=outer_padding_px,
        outer_padding_white=outer_padding_white,
    )
