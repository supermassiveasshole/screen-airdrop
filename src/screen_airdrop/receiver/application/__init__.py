"""Receiver application-layer entrypoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.receiver.application.pipeline_factory import create_pipeline
    from screen_airdrop.receiver.application.restore import restore_payload

__all__ = ["create_pipeline", "restore_payload"]


def __getattr__(name):
    if name == "create_pipeline":
        from screen_airdrop.receiver.application.pipeline_factory import create_pipeline

        return create_pipeline
    if name == "restore_payload":
        from screen_airdrop.receiver.application.restore import restore_payload

        return restore_payload
    raise AttributeError(name)
