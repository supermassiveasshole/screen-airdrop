"""Compact receiver transport package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.receiver.transport.compact.adapter import CompactProtocolDecoder
    from screen_airdrop.receiver.transport.compact.decoder import (
        DecodeMetaCompact,
        decode_frame_compact,
    )
    from screen_airdrop.receiver.transport.compact.detector import detect_symbol_quad_compact

__all__ = [
    "CompactProtocolDecoder",
    "DecodeMetaCompact",
    "decode_frame_compact",
    "detect_symbol_quad_compact",
]


def __getattr__(name):
    if name == "CompactProtocolDecoder":
        from screen_airdrop.receiver.transport.compact.adapter import CompactProtocolDecoder

        return CompactProtocolDecoder
    if name in {"DecodeMetaCompact", "decode_frame_compact"}:
        from screen_airdrop.receiver.transport.compact import decoder as _decoder

        return getattr(_decoder, name)
    if name == "detect_symbol_quad_compact":
        from screen_airdrop.receiver.transport.compact import detector as _detector

        return _detector.detect_symbol_quad_compact
    raise AttributeError(name)
