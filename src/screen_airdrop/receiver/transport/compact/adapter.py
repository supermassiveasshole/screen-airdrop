"""Compact protocol decoder adapter."""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

from screen_airdrop.common.transport.protocol_interface import (
    DecodedFrame,
    LayoutInfo,
    ProtocolDecoder,
)
from screen_airdrop.receiver.transport.compact.decoder import decode_frame_compact
from screen_airdrop.receiver.transport.result_mapping import build_transport_decode_result
from screen_airdrop.sender.transport.compact.encoder import (
    build_layout_compact,
    frame_capacity_bytes_compact,
)


class CompactProtocolDecoder(ProtocolDecoder):
    """Adapter for compact protocol decoder."""

    def __init__(
        self,
        grid_w: int = 160,
        grid_h: int = 96,
        guard_band: int = 1,      # Compact default
        corner_size: int = 7,     # Compact default
        locator_engine: str = "legacy",  # Use legacy for compact (7x7 finders)
        locator_confidence_threshold: float = 0.55,
    ):
        self.grid_w = grid_w
        self.grid_h = grid_h
        self.guard_band = guard_band
        self.corner_size = corner_size
        self.locator_engine = locator_engine
        self.locator_confidence_threshold = locator_confidence_threshold

    def get_layout(self) -> LayoutInfo:
        layout = build_layout_compact(
            grid_w=self.grid_w,
            grid_h=self.grid_h,
            guard_band=self.guard_band,
            corner_size=self.corner_size,
        )
        capacity = frame_capacity_bytes_compact(
            grid_w=self.grid_w,
            grid_h=self.grid_h,
            ecc_level="Q",
            guard_band=self.guard_band,
            corner_size=self.corner_size,
        )
        return LayoutInfo(
            frame_w=layout.frame_w,
            frame_h=layout.frame_h,
            data_capacity_bits=capacity * 8,
            header_capacity_bits=0,
            protocol_name="compact",
            protocol_version="4.0",
            bits_per_module=1,
            quiet_zone=layout.quiet,
            finder_size=layout.finder,
            guard_band=layout.guard_band,
            grid_w=self.grid_w,
            grid_h=self.grid_h,
        )

    def decode_frame(
        self,
        frame: np.ndarray,
        detect_mode: str = "full",
        forced_roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> DecodedFrame:
        header, payload, meta = decode_frame_compact(
            frame=frame,
            detect_mode=detect_mode,
            forced_roi=forced_roi,
            grid_w=self.grid_w,
            grid_h=self.grid_h,
            guard_band=self.guard_band,
            corner_size=self.corner_size,
            locator_engine=self.locator_engine,
            locator_confidence_threshold=self.locator_confidence_threshold,
        )
        return build_transport_decode_result(header, payload, meta)
