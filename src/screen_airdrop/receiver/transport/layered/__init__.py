"""Layered receiver transport package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.receiver.transport.layered.adapter import LayeredProtocolDecoder
    from screen_airdrop.receiver.transport.layered.decoder import (
        DecodeMetaLayered,
        LayeredGeometryState,
        decode_frame_layered,
    )
    from screen_airdrop.receiver.transport.layered.observability import LayeredReportAdapter

__all__ = [
    "DecodeMetaLayered",
    "LayeredGeometryState",
    "LayeredProtocolDecoder",
    "LayeredReportAdapter",
    "decode_frame_layered",
]


def __getattr__(name):
    if name == "LayeredProtocolDecoder":
        from screen_airdrop.receiver.transport.layered.adapter import LayeredProtocolDecoder

        return LayeredProtocolDecoder
    if name in {"DecodeMetaLayered", "LayeredGeometryState", "decode_frame_layered"}:
        from screen_airdrop.receiver.transport.layered import decoder as _decoder

        return getattr(_decoder, name)
    if name == "LayeredReportAdapter":
        from screen_airdrop.receiver.transport.layered.observability import LayeredReportAdapter

        return LayeredReportAdapter
    raise AttributeError(name)
