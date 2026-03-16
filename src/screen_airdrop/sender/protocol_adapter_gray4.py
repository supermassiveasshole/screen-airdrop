"""Gray4 protocol encoder adapter."""

from __future__ import annotations

from typing import List, Tuple

import numpy as np

from screen_airdrop.common.control_plane import control_kind_from_wire_chunk_id
from screen_airdrop.common.protocol_basic import (
    ECC_TO_REP,
    FRAME_DATA,
    FRAME_SYNC,
    HEADER_SIZE,
    FrameHeaderBasic,
)
from screen_airdrop.common.protocol_interface import LayoutInfo, ProtocolEncoder
from screen_airdrop.sender.encoder_gray4 import (
    build_layout_gray4,
    encode_frame_gray4,
    frame_capacity_bytes_gray4,
    gray4_header_repetition,
)


class Gray4ProtocolEncoder(ProtocolEncoder):
    """Adapter for gray4 protocol encoder (compact geometry, 4-level payload)."""

    @staticmethod
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

    @staticmethod
    def _header_bits(frame_header: FrameHeaderBasic, rep: int) -> List[int]:
        bits: List[int] = []
        for value in frame_header.pack():
            for shift in range(7, -1, -1):
                bit = (int(value) >> shift) & 1
                for _ in range(rep):
                    bits.append(bit)
        return bits

    @classmethod
    def _header_mask_score(
        cls,
        frame_header: FrameHeaderBasic,
        header_coords: List[Tuple[int, int]],
        rep: int,
        mask_id: int,
    ) -> Tuple[int, int, int]:
        bits = cls._header_bits(frame_header, rep)
        masked_bits: List[int] = []
        for idx, (x, y) in enumerate(header_coords[: len(bits)]):
            bit = bits[idx]
            if cls._mask_bit(mask_id, x, y):
                bit ^= 1
            masked_bits.append(bit)
        if not masked_bits:
            return (0, 0, 0)
        ones = sum(masked_bits)
        zeros = len(masked_bits) - ones
        transitions = sum(
            1 for idx in range(1, len(masked_bits)) if masked_bits[idx] != masked_bits[idx - 1]
        )
        balance_penalty = abs(ones - zeros)
        return (-balance_penalty, transitions, -int(mask_id))

    def _candidate_masks(self, frame_header: FrameHeaderBasic) -> List[int]:
        seed = int(frame_header.chunk_id + frame_header.epoch_id + frame_header.frame_id) & 7
        candidates: List[int] = []
        for offset in (0, 3, 5):
            candidate = (seed + offset) & 7
            if candidate not in candidates:
                candidates.append(candidate)
        return candidates

    def _select_mask(
        self,
        frame_header: FrameHeaderBasic,
        forced_mask: int | None,
    ) -> int:
        if forced_mask is not None:
            return int(forced_mask) & 7

        frame_type = int(frame_header.frame_type)
        if frame_type == int(FRAME_SYNC):
            return ((int(frame_header.frame_id) // 2) % 4) * 2
        if frame_type != int(FRAME_DATA):
            return 3
        if control_kind_from_wire_chunk_id(int(frame_header.chunk_id)) is not None:
            return 3

        rep = gray4_header_repetition(ECC_TO_REP[self.ecc_level])
        header_cell_count = HEADER_SIZE * 8 * rep
        header_coords = self._layout.data_coords[:header_cell_count]
        best_mask = None
        best_score = None
        for candidate in self._candidate_masks(frame_header):
            score = self._header_mask_score(frame_header, header_coords, rep, candidate)
            if best_score is None or score > best_score:
                best_score = score
                best_mask = candidate
        return 3 if best_mask is None else int(best_mask)

    def __init__(
        self,
        grid_w: int = 160,
        grid_h: int = 96,
        ecc_level: str = "L",  # Default to L for maximum throughput
        guard_band: int = 1,
        corner_size: int = 7,
        forced_mask: int | None = None,
        outer_padding_px: int = 0,
        outer_padding_white: bool = False,
    ):
        self.grid_w = grid_w
        self.grid_h = grid_h
        self.ecc_level = ecc_level
        self.guard_band = guard_band
        self.corner_size = corner_size
        self.forced_mask = forced_mask
        self.outer_padding_px = outer_padding_px
        self.outer_padding_white = outer_padding_white

        # Pre-compute layout
        self._layout = build_layout_gray4(
            grid_w=grid_w,
            grid_h=grid_h,
            guard_band=guard_band,
            corner_size=corner_size,
        )
        self._capacity = frame_capacity_bytes_gray4(
            grid_w=grid_w,
            grid_h=grid_h,
            ecc_level=ecc_level,
            guard_band=guard_band,
            corner_size=corner_size,
        )

    def get_layout(self) -> LayoutInfo:
        return LayoutInfo(
            frame_w=self._layout.frame_w,
            frame_h=self._layout.frame_h,
            data_capacity_bits=self._capacity * 8,
            header_capacity_bits=0,  # Header is mixed with data in gray4
            protocol_name="gray4",
            protocol_version="4.1",
            bits_per_module=2,
            quiet_zone=self._layout.quiet,
            finder_size=self._layout.finder,
            guard_band=self._layout.guard_band,
            grid_w=self.grid_w,
            grid_h=self.grid_h,
        )

    def encode_frame(
        self,
        frame_header: object,
        payload: bytes,
        width: int,
        height: int,
    ) -> np.ndarray:
        if not isinstance(frame_header, FrameHeaderBasic):
            raise TypeError("gray4 encoder requires FrameHeaderBasic header")

        # Call gray4 encoder
        return encode_frame_gray4(
            header=frame_header,
            payload=payload,
            width=width,
            height=height,
            grid_w=self.grid_w,
            grid_h=self.grid_h,
            ecc_level=self.ecc_level,
            guard_band=self.guard_band,
            corner_size=self.corner_size,
            forced_mask=self._select_mask(frame_header, self.forced_mask),
            outer_padding_px=self.outer_padding_px,
            outer_padding_white=self.outer_padding_white,
        )
