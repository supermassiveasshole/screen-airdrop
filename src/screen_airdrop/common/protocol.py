"""Binary protocol definition for frame headers and CRC handling."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from .errors import E2003, E2004, ScreenAirdropError

MAGIC = 0x53415244
PROTOCOL_VERSION_V1 = 1
PROTOCOL_VERSION_V2 = 2
PROTOCOL_VERSION = PROTOCOL_VERSION_V2

FRAME_SYNC = 0
FRAME_DATA = 1
FRAME_END = 2

LAYOUT_V2_BASIC = 1
V2_OUTER_BORDER_BLOCKS = 2
V2_LOCATOR_GAP_BLOCKS = 2
V2_INNER_BORDER_BLOCKS = 1
V2_PAYLOAD_GAP_BLOCKS = 1


def v2_payload_inset_px(block_size: int) -> int:
    return block_size * (
        V2_OUTER_BORDER_BLOCKS
        + V2_LOCATOR_GAP_BLOCKS
        + V2_INNER_BORDER_BLOCKS
        + V2_PAYLOAD_GAP_BLOCKS
    )

# v1: magic, version, frame_type, flags, session_id, epoch_id, frame_id,
# total_frames, chunk_id, payload_len, header_crc32, payload_crc32
HEADER_STRUCT_V1 = struct.Struct("<IBBHQIIIIHII")
HEADER_SIZE_V1 = HEADER_STRUCT_V1.size

# v2: + layout_id, canvas_w, canvas_h, locator_crc
HEADER_STRUCT_V2 = struct.Struct("<IBBHQIIIIHHHHIII")
HEADER_SIZE_V2 = HEADER_STRUCT_V2.size


@dataclass
class FrameHeader:
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
    layout_id: int = 0
    canvas_w: int = 0
    canvas_h: int = 0
    locator_crc: int = 0

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
        version: int = PROTOCOL_VERSION,
        layout_id: int = LAYOUT_V2_BASIC,
        canvas_w: int = 0,
        canvas_h: int = 0,
        locator_crc: int = 0,
    ) -> "FrameHeader":
        payload_crc = crc32(payload)
        header = cls(
            magic=MAGIC,
            version=version,
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
            layout_id=layout_id,
            canvas_w=canvas_w,
            canvas_h=canvas_h,
            locator_crc=locator_crc,
        )
        header.header_crc32 = header.compute_header_crc()
        return header

    def _pack_with_header_crc(self, header_crc32: int) -> bytes:
        if self.version == PROTOCOL_VERSION_V1:
            return HEADER_STRUCT_V1.pack(
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

        if self.version == PROTOCOL_VERSION_V2:
            return HEADER_STRUCT_V2.pack(
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
                self.layout_id,
                self.canvas_w,
                self.canvas_h,
                self.locator_crc,
                header_crc32,
                self.payload_crc32,
            )

        raise ScreenAirdropError(E2003, "unsupported version: {0}".format(self.version))

    def compute_header_crc(self) -> int:
        packed = self._pack_with_header_crc(0)
        return crc32(packed)

    def pack(self) -> bytes:
        return self._pack_with_header_crc(self.header_crc32)

    @classmethod
    def unpack(cls, data: bytes) -> "FrameHeader":
        if len(data) < 5:
            raise ScreenAirdropError(E2003, "header too short")

        magic = struct.unpack("<I", data[:4])[0]
        if magic != MAGIC:
            raise ScreenAirdropError(E2003, "bad magic")

        version = data[4]
        if version == PROTOCOL_VERSION_V1:
            if len(data) < HEADER_SIZE_V1:
                raise ScreenAirdropError(E2003, "v1 header too short")
            parts = HEADER_STRUCT_V1.unpack(data[:HEADER_SIZE_V1])
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
        elif version == PROTOCOL_VERSION_V2:
            if len(data) < HEADER_SIZE_V2:
                raise ScreenAirdropError(E2003, "v2 header too short")
            parts = HEADER_STRUCT_V2.unpack(data[:HEADER_SIZE_V2])
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
                layout_id=parts[10],
                canvas_w=parts[11],
                canvas_h=parts[12],
                locator_crc=parts[13],
                header_crc32=parts[14],
                payload_crc32=parts[15],
            )
        else:
            raise ScreenAirdropError(E2003, "unsupported version: {0}".format(version))

        expected = header.compute_header_crc()
        if expected != header.header_crc32:
            raise ScreenAirdropError(E2003, "header crc mismatch")
        return header


def header_size_for_version(version: int) -> int:
    if version == PROTOCOL_VERSION_V1:
        return HEADER_SIZE_V1
    if version == PROTOCOL_VERSION_V2:
        return HEADER_SIZE_V2
    raise ScreenAirdropError(E2003, "unsupported version: {0}".format(version))


def crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def validate_payload_crc(header: FrameHeader, payload: bytes) -> None:
    if crc32(payload) != header.payload_crc32:
        raise ScreenAirdropError(E2004, "payload crc mismatch")
