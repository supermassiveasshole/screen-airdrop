"""Protocol interface definitions for encoder/decoder abstraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

import numpy as np


@dataclass
class LayoutInfo:
    """Protocol layout information (sender/receiver shared)."""

    frame_w: int  # Total width (modules)
    frame_h: int  # Total height (modules)
    data_capacity_bits: int  # Single frame payload capacity (bits)
    header_capacity_bits: int  # Frame header capacity (bits)
    protocol_name: str  # "basic", "compact", etc.
    protocol_version: str  # "3.1", "4.0", etc.
    bits_per_module: int  # 1=binary, 2=4-gray

    # Optional layout details (for debugging)
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


class ProtocolEncoder:
    """Protocol encoder interface (sender side)."""

    def get_layout(self) -> LayoutInfo:
        """Return layout information."""
        raise NotImplementedError

    def encode_frame(
        self,
        frame_header: Any,
        payload: bytes,
        width: int,
        height: int,
    ) -> np.ndarray:
        """Encode single frame.

        Args:
            frame_header: Protocol-specific frame header object
            payload: Payload data (raw bytes)
            width: Output image width (pixels)
            height: Output image height (pixels)

        Returns:
            image: (H, W, 3) BGR image, dtype=np.uint8
        """
        raise NotImplementedError


class ProtocolDecoder:
    """Protocol decoder interface (receiver side)."""

    def get_layout(self) -> LayoutInfo:
        """Return layout information."""
        raise NotImplementedError

    def decode_frame(
        self,
        frame: np.ndarray,
        detect_mode: str = "full",
        forced_roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> DecodedFrame:
        """Decode single frame.

        Args:
            frame: Captured screen image (H, W, 3) BGR
            detect_mode: "full", "track", or "roi"
            forced_roi: Optional search region (x, y, w, h)

        Returns:
            Typed protocol decode result
        """
        raise NotImplementedError
