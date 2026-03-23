"""Basic sender transport package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.sender.transport.basic.adapter import BasicProtocolEncoder
    from screen_airdrop.sender.transport.basic.encoder import (
        BasicLayout,
        build_layout_basic,
        encode_frame_basic,
    )

__all__ = [
    "BasicLayout",
    "BasicProtocolEncoder",
    "build_layout_basic",
    "encode_frame_basic",
]


def __getattr__(name):
    if name == "BasicProtocolEncoder":
        from screen_airdrop.sender.transport.basic.adapter import BasicProtocolEncoder

        return BasicProtocolEncoder
    if name in {"BasicLayout", "build_layout_basic", "encode_frame_basic"}:
        from screen_airdrop.sender.transport.basic import encoder as _encoder

        return getattr(_encoder, name)
    raise AttributeError(name)
