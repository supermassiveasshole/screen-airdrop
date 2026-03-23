"""Gray4 protocol: 4-level grayscale modulation (2 bits per module)."""

from __future__ import annotations

from typing import List

from .protocol_basic import ECC_TO_REP

# Magic bytes for gray4 protocol
MAGIC_GRAY4 = 0x53415234  # "SAR4"

# Gray level mapping: symbol → pixel value
GRAY4_LEVELS = [0, 85, 170, 255]

# Quantization thresholds (midpoints between levels)
GRAY4_THRESHOLDS = [43, 128, 213]


def encode_gray4_symbols(data: bytes, capacity_symbols: int) -> List[int]:
    """
    Convert bytes to 2-bit symbols (0-3).

    Each byte produces 4 symbols:
    - bits 7-6 → symbol 0
    - bits 5-4 → symbol 1
    - bits 3-2 → symbol 2
    - bits 1-0 → symbol 3

    Args:
        data: Raw bytes to encode
        capacity_symbols: Number of 2-bit symbols available

    Returns:
        List of symbols (0-3), length = capacity_symbols
        Pads with 0 if data exhausted
    """
    symbols = []
    for byte in data:
        symbols.append((byte >> 6) & 0x03)  # bits 7-6
        symbols.append((byte >> 4) & 0x03)  # bits 5-4
        symbols.append((byte >> 2) & 0x03)  # bits 3-2
        symbols.append(byte & 0x03)         # bits 1-0

    # Pad to capacity
    while len(symbols) < capacity_symbols:
        symbols.append(0)

    return symbols[:capacity_symbols]


def decode_gray4_symbols(symbols: List[int], data_length_bytes: int) -> bytes:
    """
    Convert 2-bit symbols back to bytes.

    4 symbols → 1 byte:
    - symbol 0 (bits 7-6)
    - symbol 1 (bits 5-4)
    - symbol 2 (bits 3-2)
    - symbol 3 (bits 1-0)

    Args:
        symbols: List of decoded symbols (0-3)
        data_length_bytes: Expected output length

    Returns:
        Decoded bytes
    """
    result = bytearray()
    for i in range(0, len(symbols), 4):
        if len(result) >= data_length_bytes:
            break
        # Ensure we have 4 symbols (pad with 0 if needed)
        s0 = symbols[i] if i < len(symbols) else 0
        s1 = symbols[i + 1] if i + 1 < len(symbols) else 0
        s2 = symbols[i + 2] if i + 2 < len(symbols) else 0
        s3 = symbols[i + 3] if i + 3 < len(symbols) else 0

        byte = (
            ((s0 & 0x03) << 6) |
            ((s1 & 0x03) << 4) |
            ((s2 & 0x03) << 2) |
            (s3 & 0x03)
        )
        result.append(byte)

    return bytes(result[:data_length_bytes])


def ecc_repetition_symbols(symbols: List[int], rep: int) -> List[int]:
    """
    Apply repetition ECC to 2-bit symbols.

    Args:
        symbols: List of 2-bit symbols (0-3)
        rep: Repetition count (1=no repetition, 3=triple each symbol)

    Returns:
        Repeated symbol list
    """
    if rep <= 1:
        return list(symbols)
    out = []
    for s in symbols:
        for _ in range(rep):
            out.append(s)
    return out


def decode_repetition_symbols(symbols: List[int], rep: int) -> List[int]:
    """
    Decode repetition ECC from 2-bit symbols using majority voting.

    Args:
        symbols: List of repeated symbols
        rep: Repetition count

    Returns:
        Decoded symbols (one per rep group)
    """
    if rep <= 1:
        return list(symbols)

    n = len(symbols) // rep
    out = []
    for i in range(n):
        # Count occurrences of each symbol value (0-3)
        counts = [0, 0, 0, 0]
        base = i * rep
        for p in range(rep):
            if base + p < len(symbols):
                sym = symbols[base + p] & 0x03
                counts[sym] += 1

        # Pick symbol with highest count
        best_sym = 0
        best_count = counts[0]
        for sym in range(1, 4):
            if counts[sym] > best_count:
                best_count = counts[sym]
                best_sym = sym

        out.append(best_sym)

    return out


def encode_header_and_payload_symbols(
    header_bytes: bytes, payload: bytes, ecc_level: str
) -> List[int]:
    """
    Encode header and payload as gray4 symbols with repetition ECC.

    Args:
        header_bytes: Packed frame header
        payload: Payload bytes
        ecc_level: ECC level (L/M/Q/H)

    Returns:
        List of 2-bit symbols with repetition applied
    """
    data = header_bytes + payload
    # Calculate capacity in symbols (each byte → 4 symbols)
    capacity_symbols = len(data) * 4

    # Convert to symbols
    symbols = encode_gray4_symbols(data, capacity_symbols)

    # Apply repetition ECC
    rep = ECC_TO_REP[ecc_level]
    return ecc_repetition_symbols(symbols, rep)


def decode_header_and_payload_symbols(
    symbols: List[int], ecc_level: str, header_size: int, payload_len: int
) -> tuple[bytes, bytes]:
    """
    Decode header and payload from gray4 symbols with repetition ECC.

    Args:
        symbols: List of received symbols (possibly with repetition)
        ecc_level: ECC level (L/M/Q/H)
        header_size: Expected header size in bytes
        payload_len: Expected payload length in bytes

    Returns:
        (header_bytes, payload_bytes)
    """
    # Decode repetition
    rep = ECC_TO_REP[ecc_level]
    dec_symbols = decode_repetition_symbols(symbols, rep)

    # Convert symbols to bytes
    total_bytes = header_size + payload_len
    raw = decode_gray4_symbols(dec_symbols, total_bytes)

    # Split header and payload
    header_bytes = raw[:header_size]
    payload_bytes = raw[header_size:header_size + payload_len]

    return header_bytes, payload_bytes
