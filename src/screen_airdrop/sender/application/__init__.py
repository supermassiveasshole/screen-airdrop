"""Sender application-layer entrypoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.sender.application.controller import run_sender
    from screen_airdrop.sender.application.frame_stream import build_encoded_frames

__all__ = [
    "build_encoded_frames",
    "run_sender",
]


def __getattr__(name):
    if name == "run_sender":
        from screen_airdrop.sender.application.controller import run_sender

        return run_sender
    if name == "build_encoded_frames":
        from screen_airdrop.sender.application.frame_stream import build_encoded_frames

        return build_encoded_frames
    raise AttributeError(name)
