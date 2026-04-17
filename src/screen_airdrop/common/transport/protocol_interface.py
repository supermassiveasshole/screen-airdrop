"""Transport-layer protocol interface definitions for encoder/decoder abstraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np

from screen_airdrop.common.information import TransmissionUnit


@dataclass
class LayoutInfo:
    """Protocol layout information (sender/receiver shared)."""

    frame_w: int
    frame_h: int
    data_capacity_bits: int
    header_capacity_bits: int
    protocol_name: str
    protocol_version: str
    bits_per_module: int

    quiet_zone: int = 0
    finder_size: int = 0
    guard_band: int = 0
    grid_w: int = 0
    grid_h: int = 0


@dataclass
class DecodedFrame:
    """Typed protocol decode result."""

    frame_header: Any
    payload: bytes
    meta: Any
    control_kind: Optional[str] = None
    transmission_unit: Optional[TransmissionUnit] = None
    invalid_data_payload: bool = False
    invalid_data_reason: str = ""


TransportDecodeResult = DecodedFrame


class ProtocolEncoder:
    """Protocol encoder interface (sender side)."""

    def get_layout(self) -> LayoutInfo:
        raise NotImplementedError

    def encode_frame(
        self,
        frame_header: Any,
        payload: bytes,
        width: int,
        height: int,
    ) -> np.ndarray:
        raise NotImplementedError


class ProtocolDecoder:
    """Protocol decoder interface (receiver side)."""

    def get_layout(self) -> LayoutInfo:
        raise NotImplementedError

    def decode_frame(
        self,
        frame: np.ndarray,
        detect_mode: str = "full",
        forced_roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> DecodedFrame:
        raise NotImplementedError

    def decode_frame_with_geometry(self, frame: np.ndarray, geometry: Any) -> DecodedFrame:
        raise NotImplementedError

    def geometry_from_meta(self, meta: Any) -> Optional[Any]:
        return None

    def geometry_from_locate_result(self, locate_result: Any, generation: int) -> Optional[Any]:
        del locate_result, generation
        return None

    def probe_geometry(self, frame: np.ndarray, geometry: Any) -> Dict[str, Any]:
        del frame, geometry
        return {}

    def locate_geometry(
        self,
        frame: np.ndarray,
        detect_mode: str = "full",
        forced_roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> Any:
        del frame, detect_mode, forced_roi
        raise NotImplementedError
