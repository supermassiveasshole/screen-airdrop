"""Layered protocol encoder adapter."""

from __future__ import annotations

import numpy as np

from screen_airdrop.common.transport.protocol_basic import ECC_H, ECC_Q, FrameHeaderBasic
from screen_airdrop.common.transport.protocol_interface import LayoutInfo, ProtocolEncoder
from screen_airdrop.common.transport.protocol_layered import (
    LAYERED_BODY_PROFILE_DEFAULT,
    LAYERED_BODY_PROFILE_ROBUST,
    layered_layout_info,
)
from screen_airdrop.sender.transport.layered.encoder import (
    build_layout_layered,
    encode_frame_layered,
    frame_capacity_bytes_layered,
)


class LayeredProtocolEncoder(ProtocolEncoder):
    def __init__(
        self,
        grid_w: int = 224,
        grid_h: int = 136,
        ecc_level: str = "L",
        guard_band: int = 1,
        corner_size: int = 7,
        outer_padding_px: int = 0,
        outer_padding_white: bool = False,
    ):
        self.grid_w = grid_w
        self.grid_h = grid_h
        self.ecc_level = ecc_level
        self.guard_band = guard_band
        self.corner_size = corner_size
        self.outer_padding_px = outer_padding_px
        self.outer_padding_white = outer_padding_white
        self.body_profile_id = (
            LAYERED_BODY_PROFILE_ROBUST if ecc_level in (ECC_Q, ECC_H) else LAYERED_BODY_PROFILE_DEFAULT
        )
        self._layout = build_layout_layered(
            grid_w,
            grid_h,
            guard_band,
            corner_size,
            body_profile_id=self.body_profile_id,
        )
        self._capacity = frame_capacity_bytes_layered(
            grid_w,
            grid_h,
            guard_band,
            corner_size,
            body_profile_id=self.body_profile_id,
        )

    def get_layout(self) -> LayoutInfo:
        return layered_layout_info(
            frame_w=self._layout.base.frame_w,
            frame_h=self._layout.base.frame_h,
            data_capacity_bits=self._capacity * 8,
            quiet_zone=self._layout.base.quiet,
            finder_size=self._layout.base.finder,
            guard_band=self._layout.base.guard_band,
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
            raise TypeError("layered encoder requires FrameHeaderBasic header")
        return encode_frame_layered(
            frame_header,
            payload,
            width=width,
            height=height,
            grid_w=self.grid_w,
            grid_h=self.grid_h,
            guard_band=self.guard_band,
            corner_size=self.corner_size,
            body_profile_id=self.body_profile_id,
            outer_padding_px=self.outer_padding_px,
            outer_padding_white=self.outer_padding_white,
        )
