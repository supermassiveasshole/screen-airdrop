"""Layered sender transport package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.sender.transport.layered.adapter import LayeredProtocolEncoder
    from screen_airdrop.sender.transport.layered.encoder import (
        LayeredLayout,
        build_layout_layered,
        encode_frame_layered,
    )

__all__ = [
    "LayeredLayout",
    "LayeredProtocolEncoder",
    "build_layout_layered",
    "encode_frame_layered",
]


def __getattr__(name):
    if name == "LayeredProtocolEncoder":
        from screen_airdrop.sender.transport.layered.adapter import LayeredProtocolEncoder

        return LayeredProtocolEncoder
    if name in {"LayeredLayout", "build_layout_layered", "encode_frame_layered"}:
        from screen_airdrop.sender.transport.layered import encoder as _encoder

        return getattr(_encoder, name)
    raise AttributeError(name)
