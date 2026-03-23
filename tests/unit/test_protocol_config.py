"""Tests for protocol_config module."""

from screen_airdrop.receiver.transport.config import PROTOCOL_GEOMETRY, get_protocol_geometry


def test_protocol_geometry_constants():
    """Test PROTOCOL_GEOMETRY constant values."""
    assert PROTOCOL_GEOMETRY["basic"] == (2, 9)
    assert PROTOCOL_GEOMETRY["compact"] == (1, 7)
    assert PROTOCOL_GEOMETRY["gray4"] == (1, 7)
    assert PROTOCOL_GEOMETRY["layered"] == (1, 7)


def test_get_protocol_geometry_basic():
    """Test get_protocol_geometry for basic protocol."""
    guard_band, corner_size = get_protocol_geometry("basic")
    assert guard_band == 2
    assert corner_size == 9


def test_get_protocol_geometry_compact():
    """Test get_protocol_geometry for compact protocol."""
    guard_band, corner_size = get_protocol_geometry("compact")
    assert guard_band == 1
    assert corner_size == 7


def test_get_protocol_geometry_gray4():
    """Test get_protocol_geometry for gray4 protocol."""
    guard_band, corner_size = get_protocol_geometry("gray4")
    assert guard_band == 1
    assert corner_size == 7


def test_get_protocol_geometry_layered():
    """Test get_protocol_geometry for layered protocol."""
    guard_band, corner_size = get_protocol_geometry("layered")
    assert guard_band == 1
    assert corner_size == 7


def test_get_protocol_geometry_unknown():
    """Test get_protocol_geometry for unknown protocol returns default."""
    guard_band, corner_size = get_protocol_geometry("unknown")
    assert guard_band == 2
    assert corner_size == 9


def test_get_protocol_geometry_empty_string():
    """Test get_protocol_geometry for empty string returns default."""
    guard_band, corner_size = get_protocol_geometry("")
    assert guard_band == 2
    assert corner_size == 9
