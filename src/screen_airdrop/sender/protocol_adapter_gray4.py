"""Gray4 protocol encoder adapter."""

from __future__ import annotations

import numpy as np

from screen_airdrop.common.protocol_basic import FRAME_DATA, FrameHeaderBasic
from screen_airdrop.common.protocol_interface import LayoutInfo, ProtocolEncoder
from screen_airdrop.sender.encoder_gray4 import (
    build_layout_gray4,
    encode_frame_gray4,
    frame_capacity_bytes_gray4,
)


class Gray4ProtocolEncoder(ProtocolEncoder):
    """Adapter for gray4 protocol encoder (compact geometry, 4-level payload)."""

    @staticmethod
    def _select_mask(frame_header: FrameHeaderBasic, forced_mask: int | None) -> int:
        if forced_mask is not None:
            return int(forced_mask) & 7

        frame_type = int(frame_header.frame_type)
        if frame_type != int(FRAME_DATA):
            return 3

        # Data-frame retries should not keep exactly the same visual realization.
        # Include frame_id so future same-window retransmissions can also vary.
        return int(frame_header.chunk_id + frame_header.epoch_id + frame_header.frame_id) & 7

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
