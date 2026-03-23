"""Compact sender transport package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.sender.transport.compact.adapter import CompactProtocolEncoder
    from screen_airdrop.sender.transport.compact.encoder import (
        CompactLayout,
        build_layout_compact,
        encode_frame_compact,
    )

__all__ = [
    "CompactLayout",
    "CompactProtocolEncoder",
    "build_layout_compact",
    "encode_frame_compact",
]


def __getattr__(name):
    if name == "CompactProtocolEncoder":
        from screen_airdrop.sender.transport.compact.adapter import CompactProtocolEncoder

        return CompactProtocolEncoder
    if name in {"CompactLayout", "build_layout_compact", "encode_frame_compact"}:
        from screen_airdrop.sender.transport.compact import encoder as _encoder

        return getattr(_encoder, name)
    raise AttributeError(name)
