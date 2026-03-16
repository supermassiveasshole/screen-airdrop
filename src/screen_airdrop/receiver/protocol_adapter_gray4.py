"""Gray4 protocol decoder adapter."""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np

from screen_airdrop.common.protocol_interface import DecodedFrame, LayoutInfo, ProtocolDecoder
from screen_airdrop.receiver.decoder_gray4 import decode_frame_gray4
from screen_airdrop.sender.encoder_gray4 import build_layout_gray4, frame_capacity_bytes_gray4


class Gray4ProtocolDecoder(ProtocolDecoder):
    """Adapter for gray4 protocol decoder (4-level grayscale, 2 bits/module)."""

    def __init__(
        self,
        grid_w: int = 160,
        grid_h: int = 96,
        guard_band: int = 1,
        corner_size: int = 7,
        locator_engine: str = "auto",
        locator_confidence_threshold: float = 0.55,
        shared_calibration_by_mask: Optional[Dict[int, np.ndarray]] = None,
    ):
        self.grid_w = grid_w
        self.grid_h = grid_h
        self.guard_band = guard_band
        self.corner_size = corner_size
        self.locator_engine = locator_engine
        self.locator_confidence_threshold = locator_confidence_threshold
        self._calibration_by_mask = shared_calibration_by_mask if shared_calibration_by_mask is not None else {}

    def get_layout(self) -> LayoutInfo:
        layout = build_layout_gray4(
            grid_w=self.grid_w,
            grid_h=self.grid_h,
            guard_band=self.guard_band,
            corner_size=self.corner_size,
        )
        capacity = frame_capacity_bytes_gray4(
            grid_w=self.grid_w,
            grid_h=self.grid_h,
            ecc_level="L",
            guard_band=self.guard_band,
            corner_size=self.corner_size,
        )
        return LayoutInfo(
            frame_w=layout.frame_w,
            frame_h=layout.frame_h,
            data_capacity_bits=capacity * 8,
            header_capacity_bits=0,
            protocol_name="gray4",
            protocol_version="4.1",
            bits_per_module=2,
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
        header, payload, meta = decode_frame_gray4(
            frame=frame,
            detect_mode=detect_mode,
            forced_roi=forced_roi,
            grid_w=self.grid_w,
            grid_h=self.grid_h,
            guard_band=self.guard_band,
            corner_size=self.corner_size,
            locator_engine=self.locator_engine,
            locator_confidence_threshold=self.locator_confidence_threshold,
            calibration_by_mask=self._calibration_by_mask,
        )
        if getattr(meta, "calibration_centers", None):
            self._calibration_by_mask[int(meta.mask_id)] = np.array(
                meta.calibration_centers, dtype=np.float32
            )
        return DecodedFrame(frame_header=header, payload=payload, meta=meta)
