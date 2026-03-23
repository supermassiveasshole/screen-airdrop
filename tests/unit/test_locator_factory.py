"""Tests for registry-backed locator factory helpers."""

from unittest.mock import MagicMock

import pytest

from screen_airdrop.receiver.locator.factory import (
    ProtocolGeometryLocator,
    build_frame_locator,
    build_protocol_geometry_locator,
    create_frame_locator,
    get_frame_locator_builder,
    get_geometry_locator_builder,
    registered_frame_locator_kinds,
    registered_geometry_locator_kinds,
)
from screen_airdrop.receiver.locator.frame_locator import FrameLocator


def test_registered_frame_locator_kinds_include_default_modes():
    assert registered_frame_locator_kinds() == ("auto", "manual")


def test_registered_geometry_locator_kinds_include_protocol_mode():
    assert registered_geometry_locator_kinds() == ("protocol",)


def test_create_auto_frame_locator():
    locator = create_frame_locator(
        "auto",
        grid_w=160,
        grid_h=96,
        guard_band=2,
        corner_size=9,
        initial_roi=None,
    )
    assert isinstance(locator, FrameLocator)
    assert getattr(locator, "_fixed_roi") is False


def test_create_manual_frame_locator():
    locator = build_frame_locator(
        grid_w=160,
        grid_h=96,
        guard_band=2,
        corner_size=9,
        initial_roi=(1, 2, 3, 4),
        manual_mode=True,
    )
    assert isinstance(locator, FrameLocator)
    assert getattr(locator, "_fixed_roi") is True


def test_build_protocol_geometry_locator():
    decoder = MagicMock()
    locator = build_protocol_geometry_locator(decoder)
    assert isinstance(locator, ProtocolGeometryLocator)


def test_unknown_locator_kind_raises():
    with pytest.raises(ValueError, match="Unknown frame locator kind: unknown"):
        get_frame_locator_builder("unknown")


def test_unknown_geometry_locator_kind_raises():
    with pytest.raises(ValueError, match="Unknown geometry locator kind: unknown"):
        get_geometry_locator_builder("unknown")
