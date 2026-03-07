"""V3 frame protocol and light-weight ECC helpers."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Iterable, List

from .errors import E2003, E2004, ScreenAirdropError

V3_MAGIC = 0x53415233  # "SAR3"
V3_VERSION = 3

V3_FRAME_SYNC = 0
V3_FRAME_DATA = 1
V3_FRAME_END = 2

V3_FORMAT_MAGIC = 0xA35D
V3_DEFAULT_GRID_W = 160
V3_DEFAULT_GRID_H = 96
V3_QUIET_MODULES = 4
V3_FINDER_SIZE = 9
V3_ALIGNMENT_SIZE = 5
V3_TIMING_OFFSET = V3_QUIET_MODULES + V3_FINDER_SIZE + 1

V3_ECC_L = "L"
V3_ECC_M = "M"
V3_ECC_Q = "Q"
V3_ECC_H = "H"
V3_ECC_LEVELS = (V3_ECC_L, V3_ECC_M, V3_ECC_Q, V3_ECC_H)
V3_ECC_TO_REP = {
    V3_ECC_L: 1,
    V3_ECC_M: 2,
    V3_ECC_Q: 3,
    V3_ECC_H: 4,
}
V3_ECC_TO_ID = {
    V3_ECC_L: 0,
    V3_ECC_M: 1,
    V3_ECC_Q: 2,
    V3_ECC_H: 3,
}
V3_ID_TO_ECC = {v: k for k, v in V3_ECC_TO_ID.items()}

V3_HEADER_STRUCT = struct.Struct("<IBBHQIIIIHII")
V3_HEADER_SIZE = V3_HEADER_STRUCT.size

V3_FORMAT_STRUCT = struct.Struct("<HBBBBH")
V3_FORMAT_SIZE = V3_FORMAT_STRUCT.size


def crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def _bits_from_bytes(data: bytes) -> List[int]:
    out = []
    for b in data:
        for i in range(7, -1, -1):
            out.append((b >> i) & 1)
    return out


def _bytes_from_bits(bits: Iterable[int]) -> bytes:
    raw = list(int(b) & 1 for b in bits)
    valid = (len(raw) // 8) * 8
    raw = raw[:valid]
    out = bytearray()
    for i in range(0, valid, 8):
        v = 0
        for b in raw[i : i + 8]:
            v = (v << 1) | b
        out.append(v)
    return bytes(out)


def ecc_repetition(bits: List[int], rep: int) -> List[int]:
    if rep <= 1:
        return list(bits)
    out = []
    for b in bits:
        for _ in range(rep):
            out.append(b)
    return out


def decode_repetition(bits: List[int], rep: int) -> List[int]:
    if rep <= 1:
        return list(bits)
    n = len(bits) // rep
    out = []
    for i in range(n):
        score = 0
        base = i * rep
        for p in range(rep):
            score += bits[base + p]
        out.append(1 if score * 2 >= rep else 0)
    return out


def validate_payload_crc(payload_crc32: int, payload: bytes) -> None:
    if crc32(payload) != payload_crc32:
        raise ScreenAirdropError(E2004, "payload crc mismatch")


@dataclass
class FormatInfoV3:
    magic: int
    version: int
    frame_type: int
    mask_id: int
    ecc_id: int
    reserved: int = 0

    def pack(self) -> bytes:
        raw = V3_FORMAT_STRUCT.pack(
            self.magic,
            self.version,
            self.frame_type,
            self.mask_id,
            self.ecc_id,
            self.reserved,
        )
        parity = crc32(raw) & 0xFFFF
        return raw + struct.pack("<H", parity)

    @classmethod
    def unpack(cls, data: bytes) -> "FormatInfoV3":
        if len(data) < V3_FORMAT_SIZE + 2:
            raise ScreenAirdropError(E2003, "format info too short")
        raw = data[:V3_FORMAT_SIZE]
        parity_expected = struct.unpack("<H", data[V3_FORMAT_SIZE : V3_FORMAT_SIZE + 2])[0]
        parity_actual = crc32(raw) & 0xFFFF
        if parity_actual != parity_expected:
            raise ScreenAirdropError(E2003, "format parity mismatch")
        magic, version, frame_type, mask_id, ecc_id, reserved = V3_FORMAT_STRUCT.unpack(raw)
        if magic != V3_FORMAT_MAGIC:
            raise ScreenAirdropError(E2003, "bad format magic")
        return cls(
            magic=magic,
            version=version,
            frame_type=frame_type,
            mask_id=mask_id,
            ecc_id=ecc_id,
            reserved=reserved,
        )


@dataclass
class FrameHeaderV3:
    magic: int
    version: int
    frame_type: int
    flags: int
    session_id: int
    epoch_id: int
    frame_id: int
    total_frames: int
    chunk_id: int
    payload_len: int
    header_crc32: int
    payload_crc32: int

    @classmethod
    def make(
        cls,
        frame_type: int,
        session_id: int,
        epoch_id: int,
        frame_id: int,
        total_frames: int,
        chunk_id: int,
        payload: bytes,
        flags: int = 0,
    ) -> "FrameHeaderV3":
        payload_crc = crc32(payload)
        header = cls(
            magic=V3_MAGIC,
            version=V3_VERSION,
            frame_type=frame_type,
            flags=flags,
            session_id=session_id,
            epoch_id=epoch_id,
            frame_id=frame_id,
            total_frames=total_frames,
            chunk_id=chunk_id,
            payload_len=len(payload),
            header_crc32=0,
            payload_crc32=payload_crc,
        )
        header.header_crc32 = header.compute_header_crc()
        return header

    def _pack_with_crc(self, header_crc32: int) -> bytes:
        return V3_HEADER_STRUCT.pack(
            self.magic,
            self.version,
            self.frame_type,
            self.flags,
            self.session_id,
            self.epoch_id,
            self.frame_id,
            self.total_frames,
            self.chunk_id,
            self.payload_len,
            header_crc32,
            self.payload_crc32,
        )

    def compute_header_crc(self) -> int:
        return crc32(self._pack_with_crc(0))

    def pack(self) -> bytes:
        return self._pack_with_crc(self.header_crc32)

    @classmethod
    def unpack(cls, data: bytes) -> "FrameHeaderV3":
        if len(data) < V3_HEADER_SIZE:
            raise ScreenAirdropError(E2003, "v3 header too short")
        parts = V3_HEADER_STRUCT.unpack(data[:V3_HEADER_SIZE])
        header = cls(
            magic=parts[0],
            version=parts[1],
            frame_type=parts[2],
            flags=parts[3],
            session_id=parts[4],
            epoch_id=parts[5],
            frame_id=parts[6],
            total_frames=parts[7],
            chunk_id=parts[8],
            payload_len=parts[9],
            header_crc32=parts[10],
            payload_crc32=parts[11],
        )
        if header.magic != V3_MAGIC:
            raise ScreenAirdropError(E2003, "bad v3 magic")
        if header.version != V3_VERSION:
            raise ScreenAirdropError(E2003, "bad v3 version")
        if header.compute_header_crc() != header.header_crc32:
            raise ScreenAirdropError(E2003, "v3 header crc mismatch")
        return header


def encode_header_and_payload_bits(header: FrameHeaderV3, payload: bytes, ecc_level: str) -> List[int]:
    rep = V3_ECC_TO_REP[ecc_level]
    bits = _bits_from_bytes(header.pack() + payload)
    return ecc_repetition(bits, rep)


def decode_header_and_payload_bits(bits: List[int], ecc_level: str) -> tuple[FrameHeaderV3, bytes]:
    rep = V3_ECC_TO_REP[ecc_level]
    dec = decode_repetition(bits, rep)
    raw = _bytes_from_bits(dec)
    if len(raw) < V3_HEADER_SIZE:
        raise ScreenAirdropError(E2003, "v3 data too short")
    header = FrameHeaderV3.unpack(raw[:V3_HEADER_SIZE])
    payload = raw[V3_HEADER_SIZE : V3_HEADER_SIZE + header.payload_len]
    if len(payload) != header.payload_len:
        raise ScreenAirdropError(E2003, "v3 payload length mismatch")
    validate_payload_crc(header.payload_crc32, payload)
    return header, payload
