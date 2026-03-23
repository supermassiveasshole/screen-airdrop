"""Gray4 receiver transport package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.receiver.transport.gray4.adapter import Gray4ProtocolDecoder
    from screen_airdrop.receiver.transport.gray4.decoder import DecodeMetaGray4, decode_frame_gray4

__all__ = [
    "Gray4ProtocolDecoder",
    "DecodeMetaGray4",
    "decode_frame_gray4",
]


def __getattr__(name):
    if name == "Gray4ProtocolDecoder":
        from screen_airdrop.receiver.transport.gray4.adapter import Gray4ProtocolDecoder

        return Gray4ProtocolDecoder
    if name in {"DecodeMetaGray4", "decode_frame_gray4"}:
        from screen_airdrop.receiver.transport.gray4 import decoder as _decoder

        return getattr(_decoder, name)
    raise AttributeError(name)
