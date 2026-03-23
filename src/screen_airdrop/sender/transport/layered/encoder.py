"""Layered visual encoder built on gray4 geometry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

from screen_airdrop.common.ecc_rs import (
    LAYERED_BOOTSTRAP_RS,
    encode_rs_bytes,
    rs_encoded_size,
)
from screen_airdrop.common.transport.protocol_basic import (
    ECC_H,
    ECC_Q,
    FrameHeaderBasic,
    crc32,
)
from screen_airdrop.common.transport.protocol_gray4 import encode_gray4_symbols
from screen_airdrop.common.transport.protocol_layered import (
    LAYERED_BODY_PROFILE_DEFAULT,
    LAYERED_BODY_PROFILE_DENSE,
    LAYERED_BODY_PROFILE_ROBUST,
    LAYERED_BOOTSTRAP_CELL_H,
    LAYERED_BOOTSTRAP_CELL_W,
    LAYERED_BOOTSTRAP_ISOLATION_ROWS,
    LAYERED_BOOTSTRAP_PROFILE_DEFAULT,
    LAYERED_BOOTSTRAP_REFERENCE_CELLS,
    LAYERED_BOOTSTRAP_ROWS,
    LAYERED_CONTROL_CELL_TEMPLATES,
    LAYERED_CONTROL_PATH_VERSION,
    LAYERED_CONTROL_SYMBOL_BITS,
    LAYERED_MAGIC,
    LAYERED_VERSION,
    BootstrapFields,
    LayeredBodyMeta,
    build_body_raw_bytes,
    layered_body_ecc_profile,
    layered_body_overhead_bytes,
    layered_body_profile_name,
    layered_bootstrap_payload_size_bytes,
    layered_short_session_tag,
)
from screen_airdrop.sender.transport.gray4.encoder import (
    Gray4Layout,
    _mask_bit,
    _paint_static_layers,
    _render_modules_gray4,
    _write_layout_info,
    build_layout_gray4,
)


@dataclass
class LayeredLayout:
    base: Gray4Layout
    control_cells: List[List[Tuple[int, int]]]
    bootstrap_cells: List[List[Tuple[int, int]]]
    bootstrap_reference_cells: List[List[Tuple[int, int]]]
    body_coords: List[Tuple[int, int]]
    bootstrap_capacity_bits: int
    body_capacity_bytes: int
    user_payload_capacity_bytes: int


def _max_payload_bytes_for_body_capacity(body_capacity_bytes: int, body_profile_id: int) -> int:
    body_rs = layered_body_ecc_profile(body_profile_id)
    low = 0
    high = int(body_capacity_bytes)
    while low < high:
        mid = (low + high + 1) // 2
        if rs_encoded_size(body_rs, layered_body_overhead_bytes() + mid) <= body_capacity_bytes:
            low = mid
        else:
            high = mid - 1
    return low


def build_layout_layered(
    grid_w: int,
    grid_h: int,
    guard_band: int,
    corner_size: int,
    body_profile_id: int = LAYERED_BODY_PROFILE_DEFAULT,
) -> LayeredLayout:
    base = build_layout_gray4(
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=guard_band,
        corner_size=corner_size,
    )
    reserved_rows = LAYERED_BOOTSTRAP_ROWS + LAYERED_BOOTSTRAP_ISOLATION_ROWS
    if grid_h <= reserved_rows:
        raise ValueError("layered grid too short for bootstrap band")
    control_cells: List[List[Tuple[int, int]]] = []
    x_groups = max(1, base.grid_w // LAYERED_BOOTSTRAP_CELL_W)
    y_groups = max(1, LAYERED_BOOTSTRAP_ROWS // LAYERED_BOOTSTRAP_CELL_H)
    for gy in range(y_groups):
        for gx in range(x_groups):
            x0 = base.grid_x0 + gx * LAYERED_BOOTSTRAP_CELL_W
            y0 = base.grid_y0 + gy * LAYERED_BOOTSTRAP_CELL_H
            cell: List[Tuple[int, int]] = []
            for dy in range(LAYERED_BOOTSTRAP_CELL_H):
                for dx in range(LAYERED_BOOTSTRAP_CELL_W):
                    x = x0 + dx
                    y = y0 + dy
                    if x <= base.grid_x1 and y <= base.grid_y1:
                        cell.append((x, y))
            if len(cell) == LAYERED_BOOTSTRAP_CELL_W * LAYERED_BOOTSTRAP_CELL_H:
                control_cells.append(cell)

    bootstrap_coded_dibits = (
        (layered_bootstrap_payload_size_bytes() + LAYERED_BOOTSTRAP_RS.nsym) * 8
    ) // LAYERED_CONTROL_SYMBOL_BITS
    required_control_cells = bootstrap_coded_dibits + LAYERED_BOOTSTRAP_REFERENCE_CELLS
    if len(control_cells) < required_control_cells:
        raise ValueError(
            "layered grid too small for control band: "
            f"{len(control_cells)} < {required_control_cells}"
        )
    bootstrap_cells = control_cells[:bootstrap_coded_dibits]
    bootstrap_reference_cells = control_cells[
        bootstrap_coded_dibits : bootstrap_coded_dibits + LAYERED_BOOTSTRAP_REFERENCE_CELLS
    ]

    bootstrap_y_cut = base.grid_y0 + reserved_rows
    body_coords = [(x, y) for x, y in base.data_coords if y >= bootstrap_y_cut]
    body_capacity_bytes = (len(body_coords) * 2) // 8
    user_payload_capacity_bytes = _max_payload_bytes_for_body_capacity(
        body_capacity_bytes,
        body_profile_id,
    )
    return LayeredLayout(
        base=base,
        control_cells=control_cells,
        bootstrap_cells=bootstrap_cells,
        bootstrap_reference_cells=bootstrap_reference_cells,
        body_coords=body_coords,
        bootstrap_capacity_bits=len(bootstrap_cells) * LAYERED_CONTROL_SYMBOL_BITS,
        body_capacity_bytes=body_capacity_bytes,
        user_payload_capacity_bytes=user_payload_capacity_bytes,
    )


def frame_capacity_bytes_layered(
    grid_w: int,
    grid_h: int,
    guard_band: int,
    corner_size: int,
    body_profile_id: int = LAYERED_BODY_PROFILE_DEFAULT,
) -> int:
    return build_layout_layered(
        grid_w,
        grid_h,
        guard_band,
        corner_size,
        body_profile_id=body_profile_id,
    ).user_payload_capacity_bytes


def _bootstrap_mask_id(header: FrameHeaderBasic) -> int:
    if int(header.frame_type) == 0:
        return ((int(header.frame_id) // 2) % 4) * 2
    if int(header.frame_type) != 1:
        return 3
    if int(header.chunk_id) >= 0xFFFFFFFC or int(header.chunk_id) == 0:
        return 3
    return int(header.chunk_id + header.epoch_id + header.frame_id) & 7


def layered_body_profile_id_for_ecc_level(ecc_level: str) -> int:
    return LAYERED_BODY_PROFILE_ROBUST if str(ecc_level) in (ECC_Q, ECC_H) else LAYERED_BODY_PROFILE_DENSE


def _dibits_from_bytes(data: bytes) -> List[int]:
    dibits: List[int] = []
    for value in data:
        dibits.extend(
            [
                (int(value) >> 6) & 0x03,
                (int(value) >> 4) & 0x03,
                (int(value) >> 2) & 0x03,
                int(value) & 0x03,
            ]
        )
    return dibits


def _encode_bootstrap_dibits(fields: BootstrapFields) -> List[int]:
    coded = encode_rs_bytes(LAYERED_BOOTSTRAP_RS, fields.pack())
    return _dibits_from_bytes(coded)


def _paint_control_symbol(mat: np.ndarray, cell: List[Tuple[int, int]], symbol: int) -> None:
    template = LAYERED_CONTROL_CELL_TEMPLATES[int(symbol) & 0x03]
    for idx, (x, y) in enumerate(cell):
        mat[y, x] = 3 if template[idx] else 0


def _paint_bootstrap(mat: np.ndarray, layout: LayeredLayout, fields: BootstrapFields) -> None:
    dibits = _encode_bootstrap_dibits(fields)
    for idx, cell in enumerate(layout.bootstrap_cells):
        symbol = dibits[idx] if idx < len(dibits) else 0
        _paint_control_symbol(mat, cell, symbol)


def _paint_bootstrap_reference_strip(mat: np.ndarray, layout: LayeredLayout) -> None:
    for idx, cell in enumerate(layout.bootstrap_reference_cells):
        _paint_control_symbol(mat, cell, idx % len(LAYERED_CONTROL_CELL_TEMPLATES))


def _paint_sync_calibration_body(
    mat: np.ndarray,
    layout: LayeredLayout,
    body_mask_id: int,
) -> None:
    if not layout.body_coords:
        return
    x_mid = 0.5 * float(layout.base.grid_x0 + layout.base.grid_x1)
    y_mid = 0.5 * float(layout.base.grid_y0 + layout.base.grid_y1)
    for x, y in layout.body_coords:
        if y <= y_mid:
            target = 0 if x <= x_mid else 1
        else:
            target = 2 if x <= x_mid else 3
        sym = target ^ 0x03 if _mask_bit(body_mask_id, x, y) else target
        mat[y, x] = sym & 0x03


def _encode_body_symbols(
    *,
    body_raw: bytes,
    body_mask_id: int,
    layout: LayeredLayout,
    body_profile_id: int,
) -> List[int]:
    body_rs = layered_body_ecc_profile(body_profile_id)
    coded = encode_rs_bytes(body_rs, body_raw)
    if len(coded) > layout.body_capacity_bytes:
        raise ValueError("layered body exceeds coded body capacity")
    symbols = encode_gray4_symbols(coded, len(layout.body_coords))
    painted: List[int] = []
    for idx, (x, y) in enumerate(layout.body_coords):
        sym = symbols[idx] & 0x03
        if _mask_bit(body_mask_id, x, y):
            sym ^= 0x03
        painted.append(sym)
    return painted


def build_symbol_modules_layered(
    header: FrameHeaderBasic,
    payload: bytes,
    *,
    grid_w: int,
    grid_h: int,
    guard_band: int,
    corner_size: int,
    body_profile_id: int = LAYERED_BODY_PROFILE_DEFAULT,
) -> np.ndarray:
    layout = build_layout_layered(
        grid_w,
        grid_h,
        guard_band,
        corner_size,
        body_profile_id=body_profile_id,
    )
    mat = np.zeros((layout.base.frame_h, layout.base.frame_w), dtype=np.uint8)
    _paint_static_layers(mat, layout.base)

    body_mask_id = _bootstrap_mask_id(header)
    payload_len = int(len(payload))

    bootstrap = BootstrapFields(
        magic=LAYERED_MAGIC,
        version=LAYERED_VERSION,
        frame_type=int(header.frame_type),
        short_session_tag=layered_short_session_tag(int(header.session_id)),
        body_profile_id=int(body_profile_id),
        payload_len=payload_len,
        body_mask_id=body_mask_id,
    )
    _paint_bootstrap(mat, layout, bootstrap)
    _paint_bootstrap_reference_strip(mat, layout)

    if int(header.frame_type) == 0:
        _paint_sync_calibration_body(mat, layout, body_mask_id)
    elif int(header.frame_type) == 1:
        body_meta = LayeredBodyMeta(
            total_frames=int(header.total_frames),
            chunk_id=int(header.chunk_id),
            payload_crc32=crc32(payload),
            epoch_id=int(header.epoch_id),
            frame_id=int(header.frame_id),
        )
        body_raw = build_body_raw_bytes(body_meta, payload)
        body_symbols = _encode_body_symbols(
            body_raw=body_raw,
            body_mask_id=body_mask_id,
            layout=layout,
            body_profile_id=body_profile_id,
        )
        for idx, (x, y) in enumerate(layout.body_coords):
            mat[y, x] = body_symbols[idx]

    _write_layout_info(mat, layout.base)
    return mat


def encode_frame_layered(
    header: FrameHeaderBasic,
    payload: bytes,
    *,
    width: int,
    height: int,
    grid_w: int,
    grid_h: int,
    guard_band: int,
    corner_size: int,
    body_profile_id: int = LAYERED_BODY_PROFILE_DEFAULT,
    outer_padding_px: int = 0,
    outer_padding_white: bool = False,
) -> np.ndarray:
    modules = build_symbol_modules_layered(
        header,
        payload,
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=guard_band,
        corner_size=corner_size,
        body_profile_id=body_profile_id,
    )
    return _render_modules_gray4(
        modules,
        width,
        height,
        outer_padding_px=outer_padding_px,
        outer_padding_white=outer_padding_white,
    )


def layered_profile_metadata(
    body_profile_id: int = LAYERED_BODY_PROFILE_DEFAULT,
) -> dict[str, int | str]:
    body_rs = layered_body_ecc_profile(body_profile_id)
    return {
        "bootstrap_profile_id": LAYERED_BOOTSTRAP_PROFILE_DEFAULT,
        "bootstrap_ecc_profile_id": LAYERED_BOOTSTRAP_RS.profile_id,
        "body_profile_id": int(body_profile_id),
        "body_profile_name": layered_body_profile_name(body_profile_id),
        "body_ecc_profile_id": body_rs.profile_id,
        "layered_control_path_version": LAYERED_CONTROL_PATH_VERSION,
        "layered_control_band_rows": LAYERED_BOOTSTRAP_ROWS,
        "layered_core_header_raw_bytes": int(layered_bootstrap_payload_size_bytes()),
        "layered_core_header_coded_bytes": int(
            layered_bootstrap_payload_size_bytes() + LAYERED_BOOTSTRAP_RS.nsym
        ),
        "layered_core_header_ecc_nsym": int(LAYERED_BOOTSTRAP_RS.nsym),
        "layered_control_symbol_bits": int(LAYERED_CONTROL_SYMBOL_BITS),
        "layered_control_reference_cells": int(LAYERED_BOOTSTRAP_REFERENCE_CELLS),
    }


def layered_control_layout_metadata(
    grid_w: int,
    grid_h: int,
    guard_band: int,
    corner_size: int,
    body_profile_id: int = LAYERED_BODY_PROFILE_DEFAULT,
) -> dict[str, int]:
    layout = build_layout_layered(
        grid_w,
        grid_h,
        guard_band,
        corner_size,
        body_profile_id=body_profile_id,
    )
    return {
        "layered_control_band_rows": int(LAYERED_BOOTSTRAP_ROWS),
        "bootstrap_capacity_bits": int(layout.bootstrap_capacity_bits),
        "bootstrap_coded_bits": int(
            (layered_bootstrap_payload_size_bytes() + LAYERED_BOOTSTRAP_RS.nsym) * 8
        ),
        "bootstrap_coded_dibits": int(
            ((layered_bootstrap_payload_size_bytes() + LAYERED_BOOTSTRAP_RS.nsym) * 8)
            // LAYERED_CONTROL_SYMBOL_BITS
        ),
        "layered_control_reference_cells": int(LAYERED_BOOTSTRAP_REFERENCE_CELLS),
        "body_profile_id": int(body_profile_id),
        "layered_control_symbol_bits": int(LAYERED_CONTROL_SYMBOL_BITS),
    }
