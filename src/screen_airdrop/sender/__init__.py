"""Sender package organized by stable subdomains.

The sender is structured around:

1. ``cli``: user-facing entrypoints
2. ``application``: high-level orchestration
3. ``scheduling``: emission policies and control payload planning
4. ``information``: information-layer unit construction
5. ``transport``: protocol-specific visual encoders/adapters
6. ``render``: presentation backends

These subpackages are the supported sender implementation surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.sender import application, cli, information, render, scheduling, transport

__all__ = ["application", "cli", "information", "render", "scheduling", "transport"]


def __getattr__(name):
    if name in __all__:
        import importlib

        return importlib.import_module("screen_airdrop.sender." + name)
    raise AttributeError(name)
