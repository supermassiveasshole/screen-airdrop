"""Common transport-layer shared package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.common.transport.protocol_interface import (
        DecodedFrame,
        LayoutInfo,
        ProtocolDecoder,
        ProtocolEncoder,
        TransportDecodeResult,
    )

__all__ = [
    "DecodedFrame",
    "LayoutInfo",
    "ProtocolDecoder",
    "ProtocolEncoder",
    "TransportDecodeResult",
]


def __getattr__(name):
    if name in __all__:
        from screen_airdrop.common.transport import protocol_interface as _protocol_interface

        return getattr(_protocol_interface, name)
    raise AttributeError(name)
