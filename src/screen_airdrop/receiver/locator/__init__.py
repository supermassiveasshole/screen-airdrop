"""Stable locator facade for pipeline wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.receiver.locator.factory import (
        ProtocolGeometryLocator,
        build_frame_locator,
        build_protocol_geometry_locator,
        create_frame_locator,
        create_geometry_locator,
        get_frame_locator_builder,
        get_geometry_locator_builder,
        register_frame_locator_builder,
        register_geometry_locator_builder,
        registered_frame_locator_kinds,
        registered_geometry_locator_kinds,
    )
    from screen_airdrop.receiver.locator.frame_locator import FrameLocator
    from screen_airdrop.receiver.locator.interfaces import (
        GeometryTrackerProtocol,
        LocatorProtocol,
    )
    from screen_airdrop.receiver.locator.window import resolve_window_region

__all__ = [
    "FrameLocator",
    "GeometryTrackerProtocol",
    "LocatorProtocol",
    "ProtocolGeometryLocator",
    "build_frame_locator",
    "build_protocol_geometry_locator",
    "create_frame_locator",
    "create_geometry_locator",
    "get_frame_locator_builder",
    "get_geometry_locator_builder",
    "register_frame_locator_builder",
    "register_geometry_locator_builder",
    "registered_frame_locator_kinds",
    "registered_geometry_locator_kinds",
    "resolve_window_region",
]


def __getattr__(name):
    if name == "FrameLocator":
        from screen_airdrop.receiver.locator.frame_locator import FrameLocator

        return FrameLocator
    if name in {"GeometryTrackerProtocol", "LocatorProtocol"}:
        from screen_airdrop.receiver.locator import interfaces as _interfaces

        return getattr(_interfaces, name)
    if name == "resolve_window_region":
        from screen_airdrop.receiver.locator.window import resolve_window_region

        return resolve_window_region
    if name in {
        "ProtocolGeometryLocator",
        "build_frame_locator",
        "build_protocol_geometry_locator",
        "create_frame_locator",
        "create_geometry_locator",
        "get_frame_locator_builder",
        "get_geometry_locator_builder",
        "register_frame_locator_builder",
        "register_geometry_locator_builder",
        "registered_frame_locator_kinds",
        "registered_geometry_locator_kinds",
    }:
        from screen_airdrop.receiver.locator import factory as _factory

        return getattr(_factory, name)
    raise AttributeError(name)
