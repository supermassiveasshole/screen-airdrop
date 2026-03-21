# pyright: reportArgumentType=false
"""Layered protocol decoder adapter."""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np

from screen_airdrop.common.protocol_interface import DecodedFrame, LayoutInfo, ProtocolDecoder
from screen_airdrop.common.protocol_layered import layered_layout_info
from screen_airdrop.receiver.decoder_layered import (
    LayeredGeometryState,
    decode_frame_layered,
    decode_frame_layered_with_geometry,
    locate_geometry_layered,
    probe_geometry_layered,
)
from screen_airdrop.sender.encoder_layered import build_layout_layered, frame_capacity_bytes_layered


class LayeredProtocolDecoder(ProtocolDecoder):
    def __init__(
        self,
        grid_w: int = 224,
        grid_h: int = 136,
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
        layout = build_layout_layered(self.grid_w, self.grid_h, self.guard_band, self.corner_size)
        capacity = frame_capacity_bytes_layered(self.grid_w, self.grid_h, self.guard_band, self.corner_size)
        return layered_layout_info(
            frame_w=layout.base.frame_w,
            frame_h=layout.base.frame_h,
            data_capacity_bits=capacity * 8,
            quiet_zone=layout.base.quiet,
            finder_size=layout.base.finder,
            guard_band=layout.base.guard_band,
            grid_w=self.grid_w,
            grid_h=self.grid_h,
        )

    def decode_frame(
        self,
        frame: np.ndarray,
        detect_mode: str = "full",
        forced_roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> DecodedFrame:
        header, payload, meta = decode_frame_layered(
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

    def locate_geometry(
        self,
        frame: np.ndarray,
        detect_mode: str = "full",
        forced_roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> LayeredGeometryState:
        return locate_geometry_layered(
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

    def decode_frame_with_geometry(
        self,
        frame: np.ndarray,
        geometry: LayeredGeometryState,
    ) -> DecodedFrame:
        header, payload, meta = decode_frame_layered_with_geometry(
            frame=frame,
            geometry=geometry,
            grid_w=self.grid_w,
            grid_h=self.grid_h,
            guard_band=self.guard_band,
            corner_size=self.corner_size,
            calibration_by_mask=self._calibration_by_mask,
        )
        if getattr(meta, "calibration_centers", None):
            self._calibration_by_mask[int(meta.mask_id)] = np.array(
                meta.calibration_centers, dtype=np.float32
            )
        return DecodedFrame(frame_header=header, payload=payload, meta=meta)

    @staticmethod
    def geometry_from_locate_result(
        locate_result: object,
        generation: int,
    ) -> Optional[LayeredGeometryState]:
        if isinstance(locate_result, LayeredGeometryState):
            del generation
            return locate_result
        if not hasattr(locate_result, "quad_src"):
            return None
        loc = locate_result
        del generation
        return LayeredGeometryState(
            quad_src=np.array(getattr(loc, "quad_src"), copy=True),
            homography=np.array(getattr(loc, "homography"), copy=True),
            homography_inv=np.array(getattr(loc, "homography_inv"), copy=True),
            grid_bbox_std=tuple(int(v) for v in getattr(loc, "grid_bbox_std")),
            warped_shape=(
                int(getattr(loc, "warped").shape[1]),
                int(getattr(loc, "warped").shape[0]),
            ),
            locator_engine=str(getattr(loc, "locator_engine", "locator")),
            det_confidence=float(getattr(getattr(loc, "quality"), "confidence", 0.0)),
            homography_rmse=float(getattr(getattr(loc, "quality"), "warp_rmse", 0.0)),
        )

    def probe_geometry(
        self,
        frame: np.ndarray,
        geometry: LayeredGeometryState,
    ) -> Dict[str, object]:
        return probe_geometry_layered(
            frame=frame,
            geometry=geometry,
            grid_w=self.grid_w,
            grid_h=self.grid_h,
            guard_band=self.guard_band,
            corner_size=self.corner_size,
            calibration_by_mask=self._calibration_by_mask,
        )

    @staticmethod
    def geometry_from_meta(meta: object) -> Optional[LayeredGeometryState]:
        quad_src = getattr(meta, "quad_src", None)
        homography = getattr(meta, "homography", None)
        homography_inv = getattr(meta, "homography_inv", None)
        det_bbox = getattr(meta, "det_bbox", None)
        warped = getattr(meta, "locator_warped_preview", None)
        if (
            quad_src is None
            or homography is None
            or homography_inv is None
            or det_bbox is None
            or warped is None
        ):
            return None
        return LayeredGeometryState(
            quad_src=np.array(quad_src, copy=True),
            homography=np.array(homography, copy=True),
            homography_inv=np.array(homography_inv, copy=True),
            grid_bbox_std=tuple(int(v) for v in det_bbox),
            warped_shape=(int(warped.shape[1]), int(warped.shape[0])),
            locator_engine=str(getattr(meta, "locator_engine", "geometry_reuse")),
            det_confidence=float(getattr(meta, "det_confidence", 0.0)),
            homography_rmse=float(getattr(meta, "homography_rmse", 0.0)),
        )
