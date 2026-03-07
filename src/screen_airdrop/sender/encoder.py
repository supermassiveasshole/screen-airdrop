"""Frame encoder for V1/V2 layouts."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from screen_airdrop.common.protocol import (
    HEADER_SIZE_V1,
    HEADER_SIZE_V2,
    PROTOCOL_VERSION_V1,
    PROTOCOL_VERSION_V2,
    V2_INNER_BORDER_BLOCKS,
    V2_LOCATOR_GAP_BLOCKS,
    V2_OUTER_BORDER_BLOCKS,
    V2_PAYLOAD_GAP_BLOCKS,
    FrameHeader,
    crc32,
    v2_payload_inset_px,
)


@dataclass
class V2Layout:
    width: int
    height: int
    block_size: int
    quiet_zone_px: int
    outer_border_px: int
    locator_gap_px: int
    inner_border_px: int
    payload_gap_px: int
    border_px: int
    canvas_x: int
    canvas_y: int
    canvas_w: int
    canvas_h: int


def bytes_to_bits(data: bytes) -> np.ndarray:
    if not data:
        return np.zeros((0,), dtype=np.uint8)
    arr = np.frombuffer(data, dtype=np.uint8)
    return np.unpackbits(arr)


def _align_to_block(value: int, block_size: int) -> int:
    return (value // block_size) * block_size


def build_v2_layout(width: int, height: int, block_size: int, quiet_zone_px: int = 48) -> V2Layout:
    # Keep a visible safe margin from window edges to reduce edge/UI contamination.
    q = max(4 * block_size, _align_to_block(quiet_zone_px, block_size))
    outer_border = V2_OUTER_BORDER_BLOCKS * block_size
    locator_gap = V2_LOCATOR_GAP_BLOCKS * block_size
    inner_border = V2_INNER_BORDER_BLOCKS * block_size
    payload_gap = V2_PAYLOAD_GAP_BLOCKS * block_size
    border = v2_payload_inset_px(block_size)

    canvas_x = q + border
    canvas_y = q + border
    canvas_w = width - 2 * (q + border)
    canvas_h = height - 2 * (q + border)

    canvas_w = _align_to_block(canvas_w, block_size)
    canvas_h = _align_to_block(canvas_h, block_size)

    if canvas_w <= 0 or canvas_h <= 0:
        raise RuntimeError("invalid v2 layout: no room for payload canvas")

    return V2Layout(
        width=width,
        height=height,
        block_size=block_size,
        quiet_zone_px=q,
        outer_border_px=outer_border,
        locator_gap_px=locator_gap,
        inner_border_px=inner_border,
        payload_gap_px=payload_gap,
        border_px=border,
        canvas_x=canvas_x,
        canvas_y=canvas_y,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
    )


def _bits_to_grid(bits: np.ndarray, rows: int, cols: int) -> np.ndarray:
    capacity = rows * cols
    if bits.size < capacity:
        padded = np.zeros((capacity,), dtype=np.uint8)
        padded[: bits.size] = bits
        bits = padded
    elif bits.size > capacity:
        bits = bits[:capacity]
    return bits.reshape((rows, cols)).astype(np.uint8)


def _grid_to_rgb(grid: np.ndarray, block_size: int) -> np.ndarray:
    img = np.kron(grid * 255, np.ones((block_size, block_size), dtype=np.uint8))
    return np.dstack([img, img, img])


def frame_capacity_bytes(
    width: int,
    height: int,
    block_size: int,
    protocol_version: int = PROTOCOL_VERSION_V2,
    quiet_zone_px: int = 48,
) -> int:
    if protocol_version == PROTOCOL_VERSION_V1:
        cols = width // block_size
        rows = height // block_size
        bits = rows * cols
        payload_bits = bits - HEADER_SIZE_V1 * 8
        return max(0, payload_bits // 8)

    layout = build_v2_layout(width, height, block_size, quiet_zone_px=quiet_zone_px)
    cols = layout.canvas_w // block_size
    rows = layout.canvas_h // block_size
    bits = rows * cols
    payload_bits = bits - HEADER_SIZE_V2 * 8
    return max(0, payload_bits // 8)


def _draw_v2_locator(frame: np.ndarray, layout: V2Layout) -> int:
    # Multi-layer locator:
    # 1) outer border for robust global localization
    # 2) inner border nearer payload to stabilize local sampling
    x = layout.canvas_x - layout.border_px
    y = layout.canvas_y - layout.border_px
    w = layout.canvas_w + 2 * layout.border_px
    h = layout.canvas_h + 2 * layout.border_px

    ob = layout.outer_border_px
    frame[y : y + ob, x : x + w] = 255
    frame[y + h - ob : y + h, x : x + w] = 255
    frame[y : y + h, x : x + ob] = 255
    frame[y : y + h, x + w - ob : x + w] = 255

    inner_x = x + ob + layout.locator_gap_px
    inner_y = y + ob + layout.locator_gap_px
    inner_w = w - 2 * (ob + layout.locator_gap_px)
    inner_h = h - 2 * (ob + layout.locator_gap_px)
    ib = layout.inner_border_px
    frame[inner_y : inner_y + ib, inner_x : inner_x + inner_w] = 255
    frame[inner_y + inner_h - ib : inner_y + inner_h, inner_x : inner_x + inner_w] = 255
    frame[inner_y : inner_y + inner_h, inner_x : inner_x + ib] = 255
    frame[inner_y : inner_y + inner_h, inner_x + inner_w - ib : inner_x + inner_w] = 255

    # Corner anchors for stronger detection confidence.
    anchor = 3 * layout.block_size
    frame[y : y + anchor, x : x + anchor] = 255
    frame[y : y + anchor, x + w - anchor : x + w] = 255
    frame[y + h - anchor : y + h, x : x + anchor] = 255
    frame[y + h - anchor : y + h, x + w - anchor : x + w] = 255

    region = frame[y : y + h, x : x + w]
    return crc32(region.tobytes())


def encode_frame(
    header: FrameHeader,
    payload: bytes,
    width: int,
    height: int,
    block_size: int,
    quiet_zone_px: int = 48,
) -> np.ndarray:
    if header.version == PROTOCOL_VERSION_V1:
        header_bits = bytes_to_bits(header.pack())
        payload_bits = bytes_to_bits(payload)
        bits = np.concatenate([header_bits, payload_bits])

        cols = width // block_size
        rows = height // block_size
        grid = _bits_to_grid(bits, rows=rows, cols=cols)
        frame = _grid_to_rgb(grid, block_size)
        return frame[:height, :width]

    layout = build_v2_layout(width, height, block_size, quiet_zone_px=quiet_zone_px)
    base = np.zeros((height, width), dtype=np.uint8)

    locator_crc = _draw_v2_locator(base, layout)
    header.locator_crc = locator_crc
    header.canvas_w = layout.canvas_w
    header.canvas_h = layout.canvas_h
    header.header_crc32 = header.compute_header_crc()

    bits = np.concatenate([bytes_to_bits(header.pack()), bytes_to_bits(payload)])
    cols = layout.canvas_w // block_size
    rows = layout.canvas_h // block_size
    grid = _bits_to_grid(bits, rows=rows, cols=cols)
    payload_rgb = _grid_to_rgb(grid, block_size)

    y1 = layout.canvas_y
    y2 = layout.canvas_y + layout.canvas_h
    x1 = layout.canvas_x
    x2 = layout.canvas_x + layout.canvas_w

    payload_gray = payload_rgb[:, :, 0]
    base[y1:y2, x1:x2] = payload_gray

    return np.dstack([base, base, base])


def build_sync_frame(
    session_id: int,
    epoch_id: int,
    frame_id: int,
    total_frames: int,
    width: int,
    height: int,
    block_size: int,
    protocol_version: int = PROTOCOL_VERSION_V2,
    quiet_zone_px: int = 48,
):
    header = FrameHeader.make(
        frame_type=0,
        session_id=session_id,
        epoch_id=epoch_id,
        frame_id=frame_id,
        total_frames=total_frames,
        chunk_id=0,
        payload=b"",
        version=protocol_version,
    )
    return encode_frame(
        header,
        b"",
        width,
        height,
        block_size,
        quiet_zone_px=quiet_zone_px,
    )
