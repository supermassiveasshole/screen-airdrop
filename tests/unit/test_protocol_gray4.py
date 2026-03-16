"""Unit tests for gray4 protocol symbol encoding/decoding."""

from __future__ import annotations

from screen_airdrop.common.protocol_gray4 import (
    decode_gray4_symbols,
    decode_repetition_symbols,
    ecc_repetition_symbols,
    encode_gray4_symbols,
)


def test_encode_gray4_symbols_basic():
    """Test basic gray4 symbol encoding."""
    # Single byte: 0b11100100 = 0xE4
    # Should produce 4 symbols: 11, 10, 01, 00 = 3, 2, 1, 0
    data = bytes([0xE4])
    symbols = encode_gray4_symbols(data, capacity_symbols=4)
    assert symbols == [3, 2, 1, 0]


def test_encode_gray4_symbols_padding():
    """Test gray4 symbol encoding with padding."""
    data = bytes([0xFF])  # 11, 11, 11, 11 = 3, 3, 3, 3
    symbols = encode_gray4_symbols(data, capacity_symbols=8)
    assert symbols == [3, 3, 3, 3, 0, 0, 0, 0]  # Padded with zeros


def test_decode_gray4_symbols_basic():
    """Test basic gray4 symbol decoding."""
    symbols = [3, 2, 1, 0]  # 11, 10, 01, 00 = 0b11100100 = 0xE4
    data = decode_gray4_symbols(symbols, data_length_bytes=1)
    assert data == bytes([0xE4])


def test_gray4_roundtrip():
    """Test gray4 encode/decode roundtrip."""
    original = bytes([0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC, 0xDE, 0xF0])
    capacity = len(original) * 4  # 4 symbols per byte
    symbols = encode_gray4_symbols(original, capacity_symbols=capacity)
    recovered = decode_gray4_symbols(symbols, data_length_bytes=len(original))
    assert recovered == original


def test_ecc_repetition_symbols_rep1():
    """Test repetition ECC with rep=1 (no repetition)."""
    symbols = [0, 1, 2, 3]
    repeated = ecc_repetition_symbols(symbols, rep=1)
    assert repeated == [0, 1, 2, 3]


def test_ecc_repetition_symbols_rep3():
    """Test repetition ECC with rep=3."""
    symbols = [0, 1, 2, 3]
    repeated = ecc_repetition_symbols(symbols, rep=3)
    assert repeated == [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3]


def test_decode_repetition_symbols_rep1():
    """Test decoding repetition ECC with rep=1."""
    symbols = [0, 1, 2, 3]
    decoded = decode_repetition_symbols(symbols, rep=1)
    assert decoded == [0, 1, 2, 3]


def test_decode_repetition_symbols_rep3_perfect():
    """Test decoding repetition ECC with rep=3 (perfect case)."""
    symbols = [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3]
    decoded = decode_repetition_symbols(symbols, rep=3)
    assert decoded == [0, 1, 2, 3]


def test_decode_repetition_symbols_rep3_with_errors():
    """Test decoding repetition ECC with rep=3 (with errors)."""
    # First group: 0, 0, 1 -> majority is 0
    # Second group: 1, 2, 1 -> majority is 1
    # Third group: 2, 2, 3 -> majority is 2
    # Fourth group: 3, 0, 3 -> majority is 3
    symbols = [0, 0, 1, 1, 2, 1, 2, 2, 3, 3, 0, 3]
    decoded = decode_repetition_symbols(symbols, rep=3)
    assert decoded == [0, 1, 2, 3]


def test_gray4_full_pipeline_with_ecc():
    """Test full gray4 pipeline with repetition ECC."""
    original = bytes([0xAB, 0xCD])
    
    # Encode to symbols
    capacity = len(original) * 4
    symbols = encode_gray4_symbols(original, capacity_symbols=capacity)
    
    # Apply rep=3 ECC
    symbols_with_ecc = ecc_repetition_symbols(symbols, rep=3)
    assert len(symbols_with_ecc) == capacity * 3
    
    # Decode rep=3 ECC
    decoded_symbols = decode_repetition_symbols(symbols_with_ecc, rep=3)
    assert len(decoded_symbols) == capacity
    
    # Decode symbols to bytes
    recovered = decode_gray4_symbols(decoded_symbols, data_length_bytes=len(original))
    assert recovered == original


def test_gray4_all_ecc_levels():
    """Test gray4 with all ECC levels (L, M, Q, H)."""
    from screen_airdrop.common.protocol_basic import ECC_TO_REP
    
    original = bytes([0x00, 0x55, 0xAA, 0xFF])
    
    for ecc_level, rep in ECC_TO_REP.items():
        capacity = len(original) * 4
        symbols = encode_gray4_symbols(original, capacity_symbols=capacity)
        symbols_with_ecc = ecc_repetition_symbols(symbols, rep=rep)
        decoded_symbols = decode_repetition_symbols(symbols_with_ecc, rep=rep)
        recovered = decode_gray4_symbols(decoded_symbols, data_length_bytes=len(original))
        assert recovered == original, f"Failed at ECC level {ecc_level}"
