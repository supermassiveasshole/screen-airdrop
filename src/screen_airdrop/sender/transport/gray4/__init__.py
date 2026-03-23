"""Gray4 sender transport package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.sender.transport.gray4.adapter import Gray4ProtocolEncoder
    from screen_airdrop.sender.transport.gray4.encoder import (
        Gray4Layout,
        build_layout_gray4,
        encode_frame_gray4,
    )

__all__ = [
    "Gray4Layout",
    "Gray4ProtocolEncoder",
    "build_layout_gray4",
    "encode_frame_gray4",
]


def __getattr__(name):
    if name == "Gray4ProtocolEncoder":
        from screen_airdrop.sender.transport.gray4.adapter import Gray4ProtocolEncoder

        return Gray4ProtocolEncoder
    if name in {"Gray4Layout", "build_layout_gray4", "encode_frame_gray4"}:
        from screen_airdrop.sender.transport.gray4 import encoder as _encoder

        return getattr(_encoder, name)
    raise AttributeError(name)
