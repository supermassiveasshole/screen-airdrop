"""Tests for protocol_decoder_factory module."""

import pytest

from screen_airdrop.receiver.transport.basic.adapter import BasicProtocolDecoder
from screen_airdrop.receiver.transport.compact.adapter import CompactProtocolDecoder
from screen_airdrop.receiver.transport.decoder_factory import create_protocol_decoder
from screen_airdrop.receiver.transport.gray4.adapter import Gray4ProtocolDecoder
from screen_airdrop.receiver.transport.layered.adapter import LayeredProtocolDecoder


def test_create_basic_decoder():
    """Test creating basic protocol decoder."""
    decoder = create_protocol_decoder(
        protocol="basic",
        grid_w=160,
        grid_h=96,
        guard_band=2,
        corner_size=9,
    )
    assert isinstance(decoder, BasicProtocolDecoder)
    assert decoder.grid_w == 160
    assert decoder.grid_h == 96


def test_create_compact_decoder():
    """Test creating compact protocol decoder."""
    decoder = create_protocol_decoder(
        protocol="compact",
        grid_w=160,
        grid_h=96,
        guard_band=1,
        corner_size=7,
    )
    assert isinstance(decoder, CompactProtocolDecoder)
    assert decoder.grid_w == 160
    assert decoder.grid_h == 96


def test_create_gray4_decoder():
    """Test creating gray4 protocol decoder."""
    decoder = create_protocol_decoder(
        protocol="gray4",
        grid_w=160,
        grid_h=96,
        guard_band=1,
        corner_size=7,
    )
    assert isinstance(decoder, Gray4ProtocolDecoder)
    assert decoder.grid_w == 160
    assert decoder.grid_h == 96


def test_create_layered_decoder():
    """Test creating layered protocol decoder."""
    decoder = create_protocol_decoder(
        protocol="layered",
        grid_w=160,
        grid_h=96,
        guard_band=1,
        corner_size=7,
    )
    assert isinstance(decoder, LayeredProtocolDecoder)
    assert decoder.grid_w == 160
    assert decoder.grid_h == 96


def test_create_decoder_with_locator_params():
    """Test creating decoder with locator parameters."""
    decoder = create_protocol_decoder(
        protocol="gray4",
        grid_w=160,
        grid_h=96,
        guard_band=1,
        corner_size=7,
        locator_engine="new",
        locator_confidence_threshold=0.7,
    )
    assert isinstance(decoder, Gray4ProtocolDecoder)
    assert decoder.locator_engine == "new"
    assert decoder.locator_confidence_threshold == 0.7


def test_create_decoder_unknown_protocol():
    """Test creating decoder with unknown protocol raises ValueError."""
    with pytest.raises(ValueError, match="Unknown protocol: unknown"):
        create_protocol_decoder(
            protocol="unknown",
            grid_w=160,
            grid_h=96,
            guard_band=2,
            corner_size=9,
        )


def test_create_decoder_empty_protocol():
    """Test creating decoder with empty protocol raises ValueError."""
    with pytest.raises(ValueError, match="Unknown protocol: "):
        create_protocol_decoder(
            protocol="",
            grid_w=160,
            grid_h=96,
            guard_band=2,
            corner_size=9,
        )
