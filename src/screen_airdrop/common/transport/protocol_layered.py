"""Protocol constants and packing helpers for layered protocol."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import cast

from screen_airdrop.common.ecc_rs import (
    LAYERED_BODY_RS_DENSE,
    LAYERED_BODY_RS_ROBUST,
    RSEccProfile,
)
from screen_airdrop.common.transport.protocol_basic import FRAME_DATA, FRAME_END, FRAME_SYNC, crc32
from screen_airdrop.common.transport.protocol_interface import LayoutInfo

LAYERED_MAGIC = 0x534C  # "SL"
LAYERED_VERSION = 6
LAYERED_PROTOCOL_VERSION = "6.1"
LAYERED_CONTROL_PATH_VERSION = 6

LAYERED_BOOTSTRAP_PROFILE_DEFAULT = 2
LAYERED_BODY_PROFILE_DENSE = 3
LAYERED_BODY_PROFILE_ROBUST = 4
LAYERED_BODY_PROFILE_DEFAULT = LAYERED_BODY_PROFILE_DENSE
LAYERED_BOOTSTRAP_ROWS = 4
LAYERED_BOOTSTRAP_ISOLATION_ROWS = 1
LAYERED_BOOTSTRAP_CELL_W = 3
LAYERED_BOOTSTRAP_CELL_H = 2
LAYERED_BOOTSTRAP_REFERENCE_CELLS = 8
LAYERED_CONTROL_SYMBOL_BITS = 2
BOOTSTRAP_STRUCT = struct.Struct("<HBBHH")
BOOTSTRAP_CRC_SIZE = 2
BODY_META_STRUCT = struct.Struct("<IIIII")
BODY_TRAILER_SIZE = 4

LAYERED_BODY_PROFILES: dict[int, dict[str, object]] = {
    LAYERED_BODY_PROFILE_DENSE: {
        "profile_id": LAYERED_BODY_PROFILE_DENSE,
        "wire_id": 0,
        "name": "dense",
        "ecc": LAYERED_BODY_RS_DENSE,
    },
    LAYERED_BODY_PROFILE_ROBUST: {
        "profile_id": LAYERED_BODY_PROFILE_ROBUST,
        "wire_id": 1,
        "name": "robust",
        "ecc": LAYERED_BODY_RS_ROBUST,
    },
}

LAYERED_BODY_WIRE_TO_PROFILE_ID = {
    int(cast(int, info["wire_id"])): int(profile_id) for profile_id, info in LAYERED_BODY_PROFILES.items()
}
LAYERED_CONTROL_CELL_TEMPLATES: tuple[tuple[int, ...], ...] = (
    (0, 1, 1, 0, 1, 1),  # 00: left dark, right light
    (1, 0, 0, 1, 0, 0),  # 01: left light, right dark
    (0, 0, 0, 1, 1, 1),  # 10: top dark, bottom light
    (1, 1, 1, 0, 0, 0),  # 11: top light, bottom dark
)


def normalize_layered_body_profile_id(profile_id: int) -> int:
    value = int(profile_id)
    if value not in LAYERED_BODY_PROFILES:
        raise ValueError(f"unknown layered body profile id: {value}")
    return value


def layered_body_profile_name(profile_id: int) -> str:
    value = normalize_layered_body_profile_id(profile_id)
    return str(LAYERED_BODY_PROFILES[value]["name"])


def layered_body_ecc_profile(profile_id: int) -> RSEccProfile:
    value = normalize_layered_body_profile_id(profile_id)
    return LAYERED_BODY_PROFILES[value]["ecc"]  # type: ignore[return-value]


def layered_body_profile_wire_id(profile_id: int) -> int:
    value = normalize_layered_body_profile_id(profile_id)
    return int(cast(int, LAYERED_BODY_PROFILES[value]["wire_id"]))


def layered_body_profile_id_from_wire_id(wire_id: int) -> int:
    value = int(wire_id)
    if value not in LAYERED_BODY_WIRE_TO_PROFILE_ID:
        raise ValueError(f"unknown layered body wire profile id: {value}")
    return int(LAYERED_BODY_WIRE_TO_PROFILE_ID[value])


@dataclass(frozen=True)
class BootstrapFields:
    magic: int
    version: int
    frame_type: int
    short_session_tag: int
    body_profile_id: int
    payload_len: int
    body_mask_id: int

    @property
    def body_ecc_profile_id(self) -> int:
        return int(layered_body_ecc_profile(self.body_profile_id).profile_id)

    @property
    def body_profile_wire_id(self) -> int:
        return int(layered_body_profile_wire_id(self.body_profile_id))

    def pack_without_crc(self) -> bytes:
        packed_mode = (
            ((int(self.version) & 0x07) << 5)
            | ((int(self.frame_type) & 0x03) << 3)
            | (int(self.body_mask_id) & 0x07)
        )
        packed_profile = int(self.body_profile_wire_id) & 0x03
        return BOOTSTRAP_STRUCT.pack(
            int(self.magic) & 0xFFFF,
            packed_mode,
            packed_profile,
            int(self.short_session_tag) & 0xFFFF,
            int(self.payload_len) & 0xFFFF,
        )

    def pack(self) -> bytes:
        raw = self.pack_without_crc()
        return raw + struct.pack("<H", crc32(raw) & 0xFFFF)

    @classmethod
    def unpack(cls, data: bytes) -> "BootstrapFields":
        if len(data) < BOOTSTRAP_STRUCT.size + BOOTSTRAP_CRC_SIZE:
            raise ValueError("layered bootstrap too short")
        raw = data[: BOOTSTRAP_STRUCT.size]
        crc_expected = struct.unpack("<H", data[BOOTSTRAP_STRUCT.size : BOOTSTRAP_STRUCT.size + 2])[0]
        if (crc32(raw) & 0xFFFF) != crc_expected:
            raise ValueError("layered bootstrap crc mismatch")
        magic, packed_mode, packed_profile, short_session_tag, payload_len = BOOTSTRAP_STRUCT.unpack(raw)
        if packed_profile & 0xFC:
            raise ValueError("layered bootstrap reserved profile bits set")
        fields = cls(
            magic=int(magic),
            version=(int(packed_mode) >> 5) & 0x07,
            frame_type=(int(packed_mode) >> 3) & 0x03,
            body_mask_id=int(packed_mode) & 0x07,
            body_profile_id=layered_body_profile_id_from_wire_id(int(packed_profile) & 0x03),
            short_session_tag=int(short_session_tag),
            payload_len=int(payload_len),
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
    epoch_id: int
    frame_id: int

    def pack(self) -> bytes:
        return BODY_META_STRUCT.pack(
            self.total_frames,
            self.chunk_id,
            self.payload_crc32,
            self.epoch_id,
            self.frame_id,
        )

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


def layered_short_session_tag(session_id: int) -> int:
    return int(session_id) & 0xFFFF


def normalize_layered_session_id(session_id: int) -> int:
    """Normalize layered v6 session identity to the on-wire 16-bit tag."""
    return layered_short_session_tag(session_id)


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


__all__ = [
    "BODY_META_STRUCT",
    "BODY_TRAILER_SIZE",
    "BOOTSTRAP_CRC_SIZE",
    "BOOTSTRAP_STRUCT",
    "BootstrapFields",
    "LAYERED_BODY_PROFILE_DEFAULT",
    "LAYERED_BODY_PROFILE_DENSE",
    "LAYERED_BODY_PROFILE_ROBUST",
    "LAYERED_BODY_PROFILES",
    "LAYERED_BODY_WIRE_TO_PROFILE_ID",
    "LAYERED_BOOTSTRAP_CELL_H",
    "LAYERED_BOOTSTRAP_CELL_W",
    "LAYERED_BOOTSTRAP_ISOLATION_ROWS",
    "LAYERED_BOOTSTRAP_PROFILE_DEFAULT",
    "LAYERED_BOOTSTRAP_REFERENCE_CELLS",
    "LAYERED_BOOTSTRAP_ROWS",
    "LAYERED_CONTROL_CELL_TEMPLATES",
    "LAYERED_CONTROL_PATH_VERSION",
    "LAYERED_CONTROL_SYMBOL_BITS",
    "LAYERED_MAGIC",
    "LAYERED_PROTOCOL_VERSION",
    "LAYERED_VERSION",
    "LayeredBodyMeta",
    "build_body_raw_bytes",
    "decode_body_raw_bytes",
    "layered_body_ecc_profile",
    "layered_body_overhead_bytes",
    "layered_body_profile_id_from_wire_id",
    "layered_body_profile_name",
    "layered_body_profile_wire_id",
    "layered_bootstrap_payload_size_bytes",
    "layered_layout_info",
    "normalize_layered_session_id",
    "layered_short_session_tag",
    "normalize_layered_body_profile_id",
]
