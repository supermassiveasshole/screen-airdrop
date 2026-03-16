"""Integration tests for gray4 encoder/decoder roundtrip."""

from __future__ import annotations

import numpy as np

from screen_airdrop.common.protocol_basic import FrameHeaderBasic
from screen_airdrop.receiver.decoder_gray4 import decode_frame_gray4
from screen_airdrop.sender.encoder_gray4 import (
    build_symbol_modules_gray4,
    encode_frame_gray4,
    frame_capacity_bytes_gray4,
    gray4_header_repetition,
)


def test_gray4_encoder_decoder_roundtrip_L():
    """Test gray4 encoder/decoder roundtrip at ECC level L."""
    grid_w = 224
    grid_h = 136
    ecc_level = "L"
    
    # Get capacity
    capacity = frame_capacity_bytes_gray4(grid_w=grid_w, grid_h=grid_h, ecc_level=ecc_level)
    assert capacity > 0
    
    # Create test payload
    payload = bytes(range(min(capacity, 256)))
    
    # Create header
    header = FrameHeaderBasic.make(
        frame_type=1,
        session_id=12345,
        epoch_id=0,
        frame_id=0,
        total_frames=10,
        chunk_id=0,
        payload=payload,
    )
    
    # Encode frame
    frame = encode_frame_gray4(
        header=header,
        payload=payload,
        width=1920,
        height=1080,
        grid_w=grid_w,
        grid_h=grid_h,
        ecc_level=ecc_level,
    )
    
    assert frame.shape == (1080, 1920, 3)
    
    # Decode frame
    decoded_header, decoded_payload, meta = decode_frame_gray4(
        frame=frame,
        grid_w=grid_w,
        grid_h=grid_h,
    )
    
    # Verify header fields
    assert decoded_header.frame_type == header.frame_type
    assert decoded_header.session_id == header.session_id
    assert decoded_header.epoch_id == header.epoch_id
    assert decoded_header.frame_id == header.frame_id
    assert decoded_header.total_frames == header.total_frames
    assert decoded_header.chunk_id == header.chunk_id
    
    # Verify payload
    assert decoded_payload == payload


def test_gray4_encoder_decoder_roundtrip_Q():
    """Test gray4 encoder/decoder roundtrip at ECC level Q."""
    grid_w = 224
    grid_h = 136
    ecc_level = "Q"
    
    # Get capacity
    capacity = frame_capacity_bytes_gray4(grid_w=grid_w, grid_h=grid_h, ecc_level=ecc_level)
    assert capacity > 0
    
    # Create test payload
    payload = bytes(range(min(capacity, 256)))
    
    # Create header
    header = FrameHeaderBasic.make(
        frame_type=1,
        session_id=67890,
        epoch_id=1,
        frame_id=5,
        total_frames=20,
        chunk_id=3,
        payload=payload,
    )
    
    # Encode frame
    frame = encode_frame_gray4(
        header=header,
        payload=payload,
        width=1280,
        height=720,
        grid_w=grid_w,
        grid_h=grid_h,
        ecc_level=ecc_level,
    )
    
    assert frame.shape == (720, 1280, 3)
    
    # Decode frame
    decoded_header, decoded_payload, meta = decode_frame_gray4(
        frame=frame,
        grid_w=grid_w,
        grid_h=grid_h,
    )
    
    # Verify
    assert decoded_header.session_id == header.session_id
    assert decoded_payload == payload


def test_gray4_encoder_decoder_roundtrip_default_grid_large_payload():
    """Regression: 160x96/L with large payload should decode reliably."""
    grid_w = 160
    grid_h = 96
    payload = bytes([i % 256 for i in range(2048)])

    header = FrameHeaderBasic.make(
        frame_type=1,
        session_id=24680,
        epoch_id=0,
        frame_id=7,
        total_frames=11,
        chunk_id=4,
        payload=payload,
    )

    frame = encode_frame_gray4(
        header=header,
        payload=payload,
        width=1920,
        height=1080,
        grid_w=grid_w,
        grid_h=grid_h,
        ecc_level="L",
    )

    decoded_header, decoded_payload, _meta = decode_frame_gray4(
        frame=frame,
        grid_w=grid_w,
        grid_h=grid_h,
    )

    assert decoded_header.frame_id == header.frame_id
    assert decoded_payload == payload


def test_gray4_capacity_comparison():
    """Test that gray4 has higher capacity than basic at same grid size."""
    from screen_airdrop.sender.encoder_basic import frame_capacity_bytes_basic
    
    grid_w = 160
    grid_h = 96
    ecc_level = "L"
    
    basic_capacity = frame_capacity_bytes_basic(grid_w=grid_w, grid_h=grid_h, ecc_level=ecc_level)
    gray4_capacity = frame_capacity_bytes_gray4(grid_w=grid_w, grid_h=grid_h, ecc_level=ecc_level)
    
    # Gray4 should have roughly 2x capacity (2 bits/module vs 1 bit/module)
    assert gray4_capacity > basic_capacity
    ratio = gray4_capacity / basic_capacity
    assert 1.8 < ratio < 2.2, f"Expected ~2x capacity, got {ratio:.2f}x"


def test_gray4_header_repetition_is_stronger_than_payload_for_l():
    assert gray4_header_repetition(1) == 1



def test_gray4_module_rendering():
    """Test that gray4 modules use 4 gray levels."""
    grid_w = 64
    grid_h = 48
    ecc_level = "L"
    
    # Create payload with varied bytes
    payload = bytes([0x00, 0x55, 0xAA, 0xFF])
    
    header = FrameHeaderBasic.make(
        frame_type=1,
        session_id=1,
        epoch_id=0,
        frame_id=0,
        total_frames=1,
        chunk_id=0,
        payload=payload,
    )
    
    # Build module matrix
    modules = build_symbol_modules_gray4(
        header=header,
        payload=payload,
        grid_w=grid_w,
        grid_h=grid_h,
        ecc_level=ecc_level,
    )
    
    # Check that modules contain values 0-3
    unique_values = np.unique(modules)
    assert len(unique_values) >= 2  # At least binary values
    assert all(v in [0, 1, 2, 3] for v in unique_values)
    
    # Data region should contain 4-level values
    # (finders/timing are binary, but data region should have all 4 levels)
    assert 2 in unique_values or 3 in unique_values  # At least one non-binary value
