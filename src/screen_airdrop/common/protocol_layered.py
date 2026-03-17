"""Protocol constants and packing helpers for layered protocol."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from screen_airdrop.common.protocol_basic import FRAME_DATA, FRAME_END, FRAME_SYNC, crc32
from screen_airdrop.common.protocol_interface import LayoutInfo

LAYERED_MAGIC = 0x5341524C  # "SARL"
LAYERED_VERSION = 4
LAYERED_PROTOCOL_VERSION = "5.3"
LAYERED_CONTROL_PATH_VERSION = 4

LAYERED_BODY_PROFILE_DEFAULT = 1
LAYERED_BOOTSTRAP_PROFILE_DEFAULT = 2
LAYERED_BOOTSTRAP_ROWS = 12
LAYERED_BOOTSTRAP_ISOLATION_ROWS = 1
LAYERED_BOOTSTRAP_CELL_W = 3
LAYERED_BOOTSTRAP_CELL_H = 2
LAYERED_BOOTSTRAP_REFERENCE_CELLS = 16
BOOTSTRAP_STRUCT = struct.Struct("<IBQHHHH")
BOOTSTRAP_CRC_SIZE = 4
BODY_META_STRUCT = struct.Struct("<III")
BODY_TRAILER_SIZE = 4


@dataclass(frozen=True)
class BootstrapFields:
    magic: int
    version: int
    frame_type: int
    session_id: int
    epoch_id: int
    frame_id: int
    payload_len: int
    body_coded_len: int
    body_mask_id: int

    def pack_without_crc(self) -> bytes:
        packed_mode = (
            ((int(self.version) & 0x07) << 5)
            | ((int(self.frame_type) & 0x03) << 3)
            | (int(self.body_mask_id) & 0x07)
        )
        return BOOTSTRAP_STRUCT.pack(
            self.magic,
            packed_mode,
            self.session_id,
            self.epoch_id,
            self.frame_id,
            self.payload_len,
            self.body_coded_len,
        )

    def pack(self) -> bytes:
        raw = self.pack_without_crc()
        return raw + struct.pack("<I", crc32(raw))

    @classmethod
    def unpack(cls, data: bytes) -> "BootstrapFields":
        if len(data) < BOOTSTRAP_STRUCT.size + BOOTSTRAP_CRC_SIZE:
            raise ValueError("layered bootstrap too short")
        raw = data[: BOOTSTRAP_STRUCT.size]
        crc_expected = struct.unpack("<I", data[BOOTSTRAP_STRUCT.size : BOOTSTRAP_STRUCT.size + 4])[0]
        if crc32(raw) != crc_expected:
            raise ValueError("layered bootstrap crc mismatch")
        parts = BOOTSTRAP_STRUCT.unpack(raw)
        packed_mode = int(parts[1])
        fields = cls(
            magic=int(parts[0]),
            version=(packed_mode >> 5) & 0x07,
            frame_type=(packed_mode >> 3) & 0x03,
            body_mask_id=packed_mode & 0x07,
            session_id=int(parts[2]),
            epoch_id=int(parts[3]),
            frame_id=int(parts[4]),
            payload_len=int(parts[5]),
            body_coded_len=int(parts[6]),
        )
        if fields.magic != LAYERED_MAGIC:
            raise ValueError("bad layered bootstrap magic")
        if fields.version != LAYERED_VERSION:
            raise ValueError("bad layered bootstrap version")
        if fields.frame_type not in (FRAME_SYNC, FRAME_DATA, FRAME_END):
            raise ValueError("bad layered frame type")
        return fields

@dataclass(frozen=True)
class LayeredBodyMeta:
    total_frames: int
    chunk_id: int
    payload_crc32: int

    def pack(self) -> bytes:
        return BODY_META_STRUCT.pack(self.total_frames, self.chunk_id, self.payload_crc32)

    @classmethod
    def unpack(cls, data: bytes) -> "LayeredBodyMeta":
        if len(data) < BODY_META_STRUCT.size:
            raise ValueError("layered body meta too short")
        return cls(*BODY_META_STRUCT.unpack(data[: BODY_META_STRUCT.size]))


def build_body_raw_bytes(meta: LayeredBodyMeta, payload: bytes) -> bytes:
    body_plain = meta.pack() + payload
    return body_plain + struct.pack("<I", crc32(body_plain))


def decode_body_raw_bytes(data: bytes, payload_len: int) -> tuple[LayeredBodyMeta, bytes]:
    min_len = BODY_META_STRUCT.size + payload_len + BODY_TRAILER_SIZE
    if len(data) < min_len:
        raise ValueError("layered body too short")
    body_plain = data[: BODY_META_STRUCT.size + payload_len]
    trailer = data[BODY_META_STRUCT.size + payload_len : min_len]
    body_crc_expected = struct.unpack("<I", trailer)[0]
    if crc32(body_plain) != body_crc_expected:
        raise ValueError("layered body crc mismatch")
    meta = LayeredBodyMeta.unpack(body_plain[: BODY_META_STRUCT.size])
    payload = body_plain[BODY_META_STRUCT.size : BODY_META_STRUCT.size + payload_len]
    return meta, payload


def layered_bootstrap_payload_size_bytes() -> int:
    return BOOTSTRAP_STRUCT.size + BOOTSTRAP_CRC_SIZE

def layered_body_overhead_bytes() -> int:
    return BODY_META_STRUCT.size + BODY_TRAILER_SIZE


def layered_layout_info(
    *,
    frame_w: int,
    frame_h: int,
    data_capacity_bits: int,
    quiet_zone: int,
    finder_size: int,
    guard_band: int,
    grid_w: int,
    grid_h: int,
) -> LayoutInfo:
    return LayoutInfo(
        frame_w=frame_w,
        frame_h=frame_h,
        data_capacity_bits=data_capacity_bits,
        header_capacity_bits=0,
        protocol_name="layered",
        protocol_version=LAYERED_PROTOCOL_VERSION,
        bits_per_module=2,
        quiet_zone=quiet_zone,
        finder_size=finder_size,
        guard_band=guard_band,
        grid_w=grid_w,
        grid_h=grid_h,
    )
