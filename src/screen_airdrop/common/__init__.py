"""Shared cross-domain primitives compatible with Python 3.7+.

This package is organized around three long-lived domains:

1. ``transport``: current visual frame/header/layout contracts
2. ``information``: future OGRB information-layer models
3. ``scheduling``: future OGRB scheduling-layer interfaces

``screen_airdrop.common.transport`` is the supported transport implementation
surface inside the repository.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.common import information, scheduling, transport

__all__ = ["information", "scheduling", "transport"]


def __getattr__(name):
    if name in __all__:
        import importlib

        return importlib.import_module("screen_airdrop.common." + name)
    raise AttributeError(name)
