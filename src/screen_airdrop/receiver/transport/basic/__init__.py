"""Basic receiver transport package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.receiver.transport.basic.adapter import BasicProtocolDecoder
    from screen_airdrop.receiver.transport.basic.decoder import (
        DecodeMetaBasic,
        decode_frame_basic,
    )
    from screen_airdrop.receiver.transport.basic.detector import (
        detect_symbol_bbox,
        detect_symbol_quad,
    )

__all__ = [
    "BasicProtocolDecoder",
    "DecodeMetaBasic",
    "decode_frame_basic",
    "detect_symbol_bbox",
    "detect_symbol_quad",
]


def __getattr__(name):
    if name == "BasicProtocolDecoder":
        from screen_airdrop.receiver.transport.basic.adapter import BasicProtocolDecoder

        return BasicProtocolDecoder
    if name in {"DecodeMetaBasic", "decode_frame_basic"}:
        from screen_airdrop.receiver.transport.basic import decoder as _decoder

        return getattr(_decoder, name)
    if name in {"detect_symbol_bbox", "detect_symbol_quad"}:
        from screen_airdrop.receiver.transport.basic import detector as _detector

        return getattr(_detector, name)
    raise AttributeError(name)
