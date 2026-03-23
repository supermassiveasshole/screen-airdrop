"""Receiver pipeline package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.receiver.pipeline.interfaces import (
        PipelineFactoryProtocol,
        PipelineProtocol,
    )
    from screen_airdrop.receiver.pipeline.runner import PipelineRunner

__all__ = [
    "PipelineFactoryProtocol",
    "PipelineProtocol",
    "PipelineRunner",
]


def __getattr__(name):
    if name in {"PipelineFactoryProtocol", "PipelineProtocol"}:
        from screen_airdrop.receiver.pipeline import interfaces as _interfaces

        return getattr(_interfaces, name)
    if name == "PipelineRunner":
        from screen_airdrop.receiver.pipeline.runner import PipelineRunner

        return PipelineRunner
    raise AttributeError(name)
