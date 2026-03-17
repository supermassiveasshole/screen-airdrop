"""Thin Reed-Solomon helpers for layered protocol."""

from __future__ import annotations

from dataclasses import dataclass

from reedsolo import ReedSolomonError, RSCodec

RS_BLOCK_SIZE = 255


@dataclass(frozen=True)
class RSEccProfile:
    profile_id: int
    nsym: int


LAYERED_BOOTSTRAP_RS = RSEccProfile(profile_id=2, nsym=16)
LAYERED_BODY_RS = RSEccProfile(profile_id=1, nsym=16)


def rs_max_data_bytes(profile: RSEccProfile) -> int:
    return RS_BLOCK_SIZE - int(profile.nsym)


def rs_encoded_size(profile: RSEccProfile, raw_len: int) -> int:
    raw_len = int(raw_len)
    if raw_len <= 0:
        return 0
    chunk = rs_max_data_bytes(profile)
    full, rem = divmod(raw_len, chunk)
    total = full * RS_BLOCK_SIZE
    if rem:
        total += rem + int(profile.nsym)
    return total


def encode_rs_bytes(profile: RSEccProfile, raw_bytes: bytes) -> bytes:
    if not raw_bytes:
        return b""
    codec = RSCodec(profile.nsym)
    chunk = rs_max_data_bytes(profile)
    encoded = bytearray()
    for offset in range(0, len(raw_bytes), chunk):
        encoded.extend(codec.encode(raw_bytes[offset : offset + chunk]))
    return bytes(encoded)


def decode_rs_bytes(profile: RSEccProfile, coded_bytes: bytes) -> tuple[bytes, int]:
    if not coded_bytes:
        return b"", 0
    codec = RSCodec(profile.nsym)
    decoded = bytearray()
    errata_count = 0
    offset = 0
    while offset < len(coded_bytes):
        remaining = len(coded_bytes) - offset
        block_len = RS_BLOCK_SIZE if remaining > RS_BLOCK_SIZE else remaining
        if block_len <= int(profile.nsym):
            raise ReedSolomonError("invalid RS block length")
        block_decoded, _full, errata = codec.decode(coded_bytes[offset : offset + block_len])
        decoded.extend(block_decoded)
        errata_count += len(bytes(errata))
        offset += block_len
    return bytes(decoded), errata_count


def decode_rs_bytes_with_erasures(
    profile: RSEccProfile,
    coded_bytes: bytes,
    erase_positions: list[int],
) -> tuple[bytes, int]:
    if not coded_bytes:
        return b"", 0
    codec = RSCodec(profile.nsym)
    decoded = bytearray()
    errata_count = 0
    offset = 0
    erase_positions = [int(pos) for pos in erase_positions]
    while offset < len(coded_bytes):
        remaining = len(coded_bytes) - offset
        block_len = RS_BLOCK_SIZE if remaining > RS_BLOCK_SIZE else remaining
        if block_len <= int(profile.nsym):
            raise ReedSolomonError("invalid RS block length")
        local_erasures = [pos - offset for pos in erase_positions if offset <= pos < offset + block_len]
        block_decoded, _full, errata = codec.decode(
            coded_bytes[offset : offset + block_len],
            erase_pos=local_erasures or None,
        )
        decoded.extend(block_decoded)
        errata_count += len(bytes(errata))
        offset += block_len
    return bytes(decoded), errata_count


__all__ = [
    "LAYERED_BOOTSTRAP_RS",
    "LAYERED_BODY_RS",
    "RSEccProfile",
    "ReedSolomonError",
    "decode_rs_bytes",
    "decode_rs_bytes_with_erasures",
    "encode_rs_bytes",
    "rs_encoded_size",
    "rs_max_data_bytes",
]
