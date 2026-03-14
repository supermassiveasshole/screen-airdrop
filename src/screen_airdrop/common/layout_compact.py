"""Layout contract for the compact protocol variant."""

from __future__ import annotations

import enum
import struct
from dataclasses import dataclass

# Global contract constants (reuse from basic)
QUAD_ORDER = ("tl", "tr", "br", "bl")
TIMING_MODE_ROWCOL = 1
LAYOUT_COMPACT_VERSION = 1

# flags
FLAG_TIMING_ENABLED = 1 << 0
FLAG_RESERVED_ALIGNMENT = 1 << 1


class LayoutInfoError(ValueError):
    """Raised when LayoutInfoCompact payload is invalid."""


class TimingMode(enum.IntEnum):
    ROWCOL = TIMING_MODE_ROWCOL


_LAYOUT_INFO_STRUCT_NOCRC = struct.Struct("<BBBBHHBB")
_LAYOUT_INFO_STRUCT = struct.Struct("<BBBBHHBBH")


# Compact protocol defaults (reduced from basic)
DEFAULT_QUIET_COMPACT = 4      # Keep same (needed for detection)
DEFAULT_FINDER_COMPACT = 7     # Reduced from 9
DEFAULT_GUARD_COMPACT = 1      # Reduced from 2
DEFAULT_GRID_W_COMPACT = 160   # Keep same initially
DEFAULT_GRID_H_COMPACT = 96    # Keep same initially


@dataclass(frozen=True)
class LayoutInfoCompact:
    """Compact protocol layout information (embedded in sync frames)."""

    layout_ver: int = LAYOUT_COMPACT_VERSION
    quiet: int = DEFAULT_QUIET_COMPACT
    finder: int = DEFAULT_FINDER_COMPACT
    guard: int = DEFAULT_GUARD_COMPACT
    grid_w: int = DEFAULT_GRID_W_COMPACT
    grid_h: int = DEFAULT_GRID_H_COMPACT
    timing_mode: int = int(TimingMode.ROWCOL)
    flags: int = FLAG_TIMING_ENABLED

    @property
    def frame_w(self) -> int:
        return int(2 * self.quiet + 2 * self.finder + 2 * self.guard + self.grid_w)

    @property
    def frame_h(self) -> int:
        return int(2 * self.quiet + 2 * self.finder + 2 * self.guard + self.grid_h)

    def validate(self) -> None:
        if self.layout_ver <= 0:
            raise LayoutInfoError("invalid layout_ver")
        if self.quiet < 1:
            raise LayoutInfoError("quiet must be >=1")
        if self.finder < 7 or self.finder % 2 == 0:
            raise LayoutInfoError("finder must be odd and >=7")
        if self.guard < 1:
            raise LayoutInfoError("guard must be >=1")
        if self.grid_w < 16 or self.grid_h < 16:
            raise LayoutInfoError("grid too small")
        if self.timing_mode != int(TimingMode.ROWCOL):
            raise LayoutInfoError("unsupported timing_mode")
        if self.flags & 0xFC:
            raise LayoutInfoError("reserved flag bits must be zero")

    def pack_without_crc(self) -> bytes:
        self.validate()
        return _LAYOUT_INFO_STRUCT_NOCRC.pack(
            int(self.layout_ver),
            int(self.quiet),
            int(self.finder),
            int(self.guard),
            int(self.grid_w),
            int(self.grid_h),
            int(self.timing_mode),
            int(self.flags),
        )

    def pack(self) -> bytes:
        head = self.pack_without_crc()
        crc = crc16_ccitt_false(head)
        return _LAYOUT_INFO_STRUCT.pack(
            int(self.layout_ver),
            int(self.quiet),
            int(self.finder),
            int(self.guard),
            int(self.grid_w),
            int(self.grid_h),
            int(self.timing_mode),
            int(self.flags),
            int(crc),
        )

    @classmethod
    def unpack(cls, data: bytes) -> "LayoutInfoCompact":
        if len(data) < _LAYOUT_INFO_STRUCT.size:
            raise LayoutInfoError("layout info too short")
        fields = _LAYOUT_INFO_STRUCT.unpack(data[: _LAYOUT_INFO_STRUCT.size])
        body = _LAYOUT_INFO_STRUCT_NOCRC.pack(*fields[:-1])
        crc_exp = int(fields[-1])
        crc_act = int(crc16_ccitt_false(body))
        if crc_exp != crc_act:
            raise LayoutInfoError("layout crc mismatch")
        layout = cls(
            layout_ver=int(fields[0]),
            quiet=int(fields[1]),
            finder=int(fields[2]),
            guard=int(fields[3]),
            grid_w=int(fields[4]),
            grid_h=int(fields[5]),
            timing_mode=int(fields[6]),
            flags=int(fields[7]),
        )
        layout.validate()
        return layout


def crc16_ccitt_false(data: bytes, init: int = 0xFFFF) -> int:
    """CRC16-CCITT-FALSE checksum (reused from basic)."""
    crc = int(init) & 0xFFFF
    for b in data:
        crc ^= (int(b) & 0xFF) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return int(crc)
