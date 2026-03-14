"""Compact protocol encoder adapter."""

from __future__ import annotations

import numpy as np

from screen_airdrop.common.protocol_basic import FrameHeaderBasic
from screen_airdrop.common.protocol_interface import LayoutInfo, ProtocolEncoder
from screen_airdrop.sender.encoder_compact import (
    build_layout_compact,
    encode_frame_compact,
    frame_capacity_bytes_compact,
)


class CompactProtocolEncoder(ProtocolEncoder):
    """Adapter for compact protocol encoder."""

    def __init__(
        self,
        grid_w: int = 160,
        grid_h: int = 96,
        ecc_level: str = "Q",
        guard_band: int = 1,      # Compact default
        corner_size: int = 7,     # Compact default
        forced_mask: int = 3,
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
        self._layout = build_layout_compact(
            grid_w=grid_w,
            grid_h=grid_h,
            guard_band=guard_band,
            corner_size=corner_size,
        )
        self._capacity = frame_capacity_bytes_compact(
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
            header_capacity_bits=0,
            protocol_name="compact",
            protocol_version="4.0",
            bits_per_module=1,
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
            raise TypeError("compact encoder requires FrameHeaderBasic header")

        return encode_frame_compact(
            header=frame_header,
            payload=payload,
            width=width,
            height=height,
            grid_w=self.grid_w,
            grid_h=self.grid_h,
            ecc_level=self.ecc_level,
            guard_band=self.guard_band,
            corner_size=self.corner_size,
            forced_mask=self.forced_mask,
            outer_padding_px=self.outer_padding_px,
            outer_padding_white=self.outer_padding_white,
        )
