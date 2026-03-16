#!/usr/bin/env python3
"""Evaluate critical-header short-code candidates on real gray4 bad frames."""

from __future__ import annotations

import argparse
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from screen_airdrop.common.protocol_basic import HEADER_SIZE, FrameHeaderBasic
from screen_airdrop.receiver.control_decode import _aggregate_threshold_scores
from screen_airdrop.receiver.decoder_gray4 import (
    _header_threshold_candidates,
    _mask_bit,
    _sample_gray4_bbox,
)
from screen_airdrop.receiver.protocol_adapter_gray4 import Gray4ProtocolDecoder
from screen_airdrop.sender.encoder_gray4 import build_layout_gray4

CRITICAL_MAGIC = 0xA35D
CRITICAL_HEADER_STRUCT = struct.Struct("<HBBHHHH")


def _crc16(data: bytes) -> int:
    value = 0xFFFF
    for byte in data:
        value ^= int(byte) << 8
        for _ in range(8):
            if value & 0x8000:
                value = ((value << 1) ^ 0x1021) & 0xFFFF
            else:
                value = (value << 1) & 0xFFFF
    return value & 0xFFFF


def _bits_from_bytes(data: bytes) -> list[int]:
    bits: list[int] = []
    for byte in data:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    return bits


def _bytes_from_bits(bits: Sequence[int]) -> bytes:
    out = bytearray()
    for i in range(0, len(bits), 8):
        value = 0
        for bit in bits[i : i + 8]:
            value = (value << 1) | (int(bit) & 1)
        out.append(value)
    return bytes(out)


def _load_frame(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".npy":
        return np.load(path)
    import cv2  # pylint: disable=import-outside-toplevel

    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError("failed to read frame: {0}".format(path))
    return frame


def _expected_bbox(
    frame: np.ndarray, frame_w_modules: int, frame_h_modules: int
) -> tuple[int, int, int, int]:
    height, width = frame.shape[:2]
    scale = max(1, min(width // frame_w_modules, height // frame_h_modules))
    symbol_w = frame_w_modules * scale
    symbol_h = frame_h_modules * scale
    ox = (width - symbol_w) // 2
    oy = (height - symbol_h) // 2
    return ox, oy, symbol_w, symbol_h


@dataclass(frozen=True)
class CriticalHeaderV0:
    magic: int
    version: int
    frame_type: int
    session_tag: int
    frame_id: int
    chunk_id: int
    payload_len: int
    crc16: int

    @classmethod
    def from_full_header(cls, header: FrameHeaderBasic) -> "CriticalHeaderV0":
        payload = CRITICAL_HEADER_STRUCT.pack(
            CRITICAL_MAGIC,
            int(header.version) & 0xFF,
            int(header.frame_type) & 0xFF,
            int(header.session_id) & 0xFFFF,
            int(header.frame_id) & 0xFFFF,
            int(header.chunk_id) & 0xFFFF,
            int(header.payload_len) & 0xFFFF,
        )
        return cls(
            magic=CRITICAL_MAGIC,
            version=int(header.version) & 0xFF,
            frame_type=int(header.frame_type) & 0xFF,
            session_tag=int(header.session_id) & 0xFFFF,
            frame_id=int(header.frame_id) & 0xFFFF,
            chunk_id=int(header.chunk_id) & 0xFFFF,
            payload_len=int(header.payload_len) & 0xFFFF,
            crc16=_crc16(payload),
        )

    def pack(self) -> bytes:
        raw = CRITICAL_HEADER_STRUCT.pack(
            self.magic,
            self.version,
            self.frame_type,
            self.session_tag,
            self.frame_id,
            self.chunk_id,
            self.payload_len,
        )
        return raw + struct.pack("<H", self.crc16)

    @classmethod
    def unpack(cls, data: bytes) -> "CriticalHeaderV0":
        if len(data) < CRITICAL_HEADER_STRUCT.size + 2:
            raise ValueError("critical header too short")
        (
            magic,
            version,
            frame_type,
            session_tag,
            frame_id,
            chunk_id,
            payload_len,
        ) = CRITICAL_HEADER_STRUCT.unpack(data[: CRITICAL_HEADER_STRUCT.size])
        crc16 = struct.unpack("<H", data[CRITICAL_HEADER_STRUCT.size : CRITICAL_HEADER_STRUCT.size + 2])[0]
        if magic != CRITICAL_MAGIC:
            raise ValueError("bad critical magic")
        raw = data[: CRITICAL_HEADER_STRUCT.size]
        if _crc16(raw) != crc16:
            raise ValueError("critical crc mismatch")
        return cls(
            magic=magic,
            version=version,
            frame_type=frame_type,
            session_tag=session_tag,
            frame_id=frame_id,
            chunk_id=chunk_id,
            payload_len=payload_len,
            crc16=crc16,
        )


TINY_HEADER_STRUCT = struct.Struct("<HBBHH")


@dataclass(frozen=True)
class TinyHeaderV0:
    magic: int
    version: int
    frame_type: int
    chunk_id: int
    payload_len: int
    crc16: int

    @classmethod
    def from_full_header(cls, header: FrameHeaderBasic) -> "TinyHeaderV0":
        payload = TINY_HEADER_STRUCT.pack(
            CRITICAL_MAGIC,
            int(header.version) & 0xFF,
            int(header.frame_type) & 0xFF,
            int(header.chunk_id) & 0xFFFF,
            int(header.payload_len) & 0xFFFF,
        )
        return cls(
            magic=CRITICAL_MAGIC,
            version=int(header.version) & 0xFF,
            frame_type=int(header.frame_type) & 0xFF,
            chunk_id=int(header.chunk_id) & 0xFFFF,
            payload_len=int(header.payload_len) & 0xFFFF,
            crc16=_crc16(payload),
        )

    def pack(self) -> bytes:
        raw = TINY_HEADER_STRUCT.pack(
            self.magic,
            self.version,
            self.frame_type,
            self.chunk_id,
            self.payload_len,
        )
        return raw + struct.pack("<H", self.crc16)

    @classmethod
    def unpack(cls, data: bytes) -> "TinyHeaderV0":
        if len(data) < TINY_HEADER_STRUCT.size + 2:
            raise ValueError("tiny header too short")
        magic, version, frame_type, chunk_id, payload_len = TINY_HEADER_STRUCT.unpack(
            data[: TINY_HEADER_STRUCT.size]
        )
        crc16 = struct.unpack("<H", data[TINY_HEADER_STRUCT.size : TINY_HEADER_STRUCT.size + 2])[0]
        if magic != CRITICAL_MAGIC:
            raise ValueError("bad tiny magic")
        raw = data[: TINY_HEADER_STRUCT.size]
        if _crc16(raw) != crc16:
            raise ValueError("tiny crc mismatch")
        return cls(
            magic=magic,
            version=version,
            frame_type=frame_type,
            chunk_id=chunk_id,
            payload_len=payload_len,
            crc16=crc16,
        )


def _encode_repetition(bits: Sequence[int], rep: int) -> list[int]:
    encoded: list[int] = []
    for bit in bits:
        encoded.extend([int(bit) & 1] * rep)
    return encoded


def _decode_repetition_from_scores(scores: Sequence[float], rep: int, message_bits: int) -> list[int]:
    decoded: list[int] = []
    for i in range(0, min(len(scores), message_bits * rep), rep):
        chunk = scores[i : i + rep]
        decoded.append(1 if float(sum(chunk)) >= 0.0 else 0)
    return decoded[:message_bits]


def _encode_hamming74(bits: Sequence[int]) -> list[int]:
    padded = list(int(bit) & 1 for bit in bits)
    while len(padded) % 4 != 0:
        padded.append(0)
    encoded: list[int] = []
    for i in range(0, len(padded), 4):
        d1, d2, d3, d4 = padded[i : i + 4]
        p1 = d1 ^ d2 ^ d4
        p2 = d1 ^ d3 ^ d4
        p3 = d2 ^ d3 ^ d4
        encoded.extend([p1, p2, d1, p3, d2, d3, d4])
    return encoded


def _decode_hamming74(bits: Sequence[int], message_bits: int) -> list[int]:
    decoded: list[int] = []
    for i in range(0, len(bits), 7):
        block = list(int(bit) & 1 for bit in bits[i : i + 7])
        if len(block) < 7:
            break
        s1 = block[0] ^ block[2] ^ block[4] ^ block[6]
        s2 = block[1] ^ block[2] ^ block[5] ^ block[6]
        s3 = block[3] ^ block[4] ^ block[5] ^ block[6]
        syndrome = s1 | (s2 << 1) | (s3 << 2)
        if syndrome:
            idx = syndrome - 1
            if 0 <= idx < 7:
                block[idx] ^= 1
        decoded.extend([block[2], block[4], block[5], block[6]])
    return decoded[:message_bits]


def _encode_secded84(bits: Sequence[int]) -> list[int]:
    padded = list(int(bit) & 1 for bit in bits)
    while len(padded) % 4 != 0:
        padded.append(0)
    encoded: list[int] = []
    for i in range(0, len(padded), 4):
        d1, d2, d3, d4 = padded[i : i + 4]
        p1 = d1 ^ d2 ^ d4
        p2 = d1 ^ d3 ^ d4
        p3 = d2 ^ d3 ^ d4
        core = [p1, p2, d1, p3, d2, d3, d4]
        p0 = 0
        for bit in core:
            p0 ^= bit
        encoded.extend([p0] + core)
    return encoded


def _decode_secded84(bits: Sequence[int], message_bits: int) -> list[int]:
    decoded: list[int] = []
    for i in range(0, len(bits), 8):
        block = list(int(bit) & 1 for bit in bits[i : i + 8])
        if len(block) < 8:
            break
        overall = 0
        for bit in block:
            overall ^= bit
        core = block[1:]
        s1 = core[0] ^ core[2] ^ core[4] ^ core[6]
        s2 = core[1] ^ core[2] ^ core[5] ^ core[6]
        s3 = core[3] ^ core[4] ^ core[5] ^ core[6]
        syndrome = s1 | (s2 << 1) | (s3 << 2)
        if syndrome and overall:
            idx = syndrome
            if idx == 0:
                block[0] ^= 1
            elif 1 <= idx <= 7:
                block[idx] ^= 1
        decoded.extend([block[3], block[5], block[6], block[7]])
    return decoded[:message_bits]


def _hard_bits_from_scores(scores: Sequence[float], code_bits: int) -> list[int]:
    return [1 if float(score) >= 0.0 else 0 for score in scores[:code_bits]]


def _placement_indices(total_cells: int, code_bits: int, mode: str, scores: Sequence[float]) -> list[int]:
    if code_bits > total_cells:
        raise ValueError("code bits exceed available cells")
    if mode == "front":
        return list(range(code_bits))
    if mode == "stride":
        if code_bits <= 1:
            return [0]
        return [
            min(total_cells - 1, int(round(i * (total_cells - 1) / float(code_bits - 1))))
            for i in range(code_bits)
        ]
    if mode == "best_abs":
        ranked = sorted(range(total_cells), key=lambda idx: abs(float(scores[idx])), reverse=True)
        return sorted(ranked[:code_bits])
    raise ValueError("unknown placement mode: {0}".format(mode))


def _candidate_table(message_bits: int) -> list[dict[str, Any]]:
    return [
        {
            "name": "critical_repetition_1",
            "encode": lambda bits: _encode_repetition(bits, 1),
            "decode_scores": lambda scores: _decode_repetition_from_scores(scores, 1, message_bits),
        },
        {
            "name": "critical_repetition_2",
            "encode": lambda bits: _encode_repetition(bits, 2),
            "decode_scores": lambda scores: _decode_repetition_from_scores(scores, 2, message_bits),
        },
        {
            "name": "critical_hamming74",
            "encode": _encode_hamming74,
            "decode_scores": lambda scores: _decode_hamming74(_hard_bits_from_scores(scores, len(scores)), message_bits),
        },
        {
            "name": "critical_secded84",
            "encode": _encode_secded84,
            "decode_scores": lambda scores: _decode_secded84(_hard_bits_from_scores(scores, len(scores)), message_bits),
        },
    ]


def _decode_sender_header(path: Path, grid_w: int, grid_h: int) -> FrameHeaderBasic:
    frame = _load_frame(path)
    decoder = Gray4ProtocolDecoder(grid_w=grid_w, grid_h=grid_h)
    decoded = decoder.decode_frame(frame, detect_mode="full")
    return decoded.frame_header


def _captured_header_scores(path: Path, grid_w: int, grid_h: int, mask_id: int) -> list[float]:
    frame = _load_frame(path)
    layout = build_layout_gray4(grid_w=grid_w, grid_h=grid_h)
    bbox = _expected_bbox(frame, layout.frame_w, layout.frame_h)
    sample_stack_u8, avg_gray_u8, _header_modules, _fixed, _adaptive, _static, _confidences = _sample_gray4_bbox(
        frame,
        bbox,
        layout,
    )
    thresholds = _header_threshold_candidates(avg_gray_u8, layout)
    header_cell_count = HEADER_SIZE * 8
    return _aggregate_threshold_scores(
        sample_stack_u8=sample_stack_u8,
        thresholds=thresholds,
        data_coords=layout.data_coords,
        header_cell_count=header_cell_count,
        repetition=1,
        mask_id=int(mask_id),
        mask_bit_fn=_mask_bit,
    )


def evaluate_pair(sender_frame: Path, captured_frame: Path, grid_w: int, grid_h: int, mask_id: int) -> dict[str, Any]:
    sender_header = _decode_sender_header(sender_frame, grid_w, grid_h)
    observed_scores = _captured_header_scores(captured_frame, grid_w, grid_h, mask_id)

    profiles = [
        ("critical_v0", CriticalHeaderV0.from_full_header(sender_header), CriticalHeaderV0.unpack),
        ("tiny_v0", TinyHeaderV0.from_full_header(sender_header), TinyHeaderV0.unpack),
    ]
    profile_results: list[dict[str, Any]] = []
    for profile_name, profile_header, unpack_header in profiles:
        profile_bits = _bits_from_bytes(profile_header.pack())
        candidate_results: list[dict[str, Any]] = []
        for candidate in _candidate_table(len(profile_bits)):
            encoded = candidate["encode"](profile_bits)
            placement_results: list[dict[str, Any]] = []
            for placement in ("front", "stride", "best_abs"):
                ok = False
                error = ""
                decoded_header: dict[str, Any] | None = None
                indices: list[int] = []
                if len(observed_scores) < len(encoded):
                    error = "insufficient observed header bits"
                else:
                    try:
                        indices = _placement_indices(len(observed_scores), len(encoded), placement, observed_scores)
                        score_slice = [float(observed_scores[idx]) for idx in indices]
                        decoded_bits = candidate["decode_scores"](score_slice)
                        decoded = unpack_header(_bytes_from_bits(decoded_bits))
                        ok = decoded == profile_header
                        decoded_header = {
                            key: int(value)
                            for key, value in vars(decoded).items()
                            if key != "crc16"
                        }
                        if not ok:
                            error = "decoded profile mismatch"
                    except Exception as exc:  # noqa: BLE001
                        error = str(exc)
                placement_results.append(
                    {
                        "placement": placement,
                        "ok": bool(ok),
                        "error": error,
                        "decoded_header": decoded_header,
                        "index_preview": indices[:12],
                    }
                )
            candidate_results.append(
                {
                    "name": candidate["name"],
                    "message_bits": int(len(profile_bits)),
                    "code_bits": int(len(encoded)),
                    "fits_current_header_cells": bool(len(encoded) <= HEADER_SIZE * 8),
                    "placements": placement_results,
                }
            )
        profile_results.append(
            {
                "profile": profile_name,
                "fields": {
                    key: int(value)
                    for key, value in vars(profile_header).items()
                    if key != "crc16"
                },
                "message_bits": int(len(profile_bits)),
                "bytes": len(profile_header.pack()),
                "candidates": candidate_results,
            }
        )

    return {
        "sender_frame": str(sender_frame),
        "captured_frame": str(captured_frame),
        "grid": {"w": int(grid_w), "h": int(grid_h)},
        "observed_header_scores": {
            "count": int(len(observed_scores)),
            "mean_abs": round(float(np.mean(np.abs(observed_scores))) if observed_scores else 0.0, 6),
            "min_abs": round(float(np.min(np.abs(observed_scores))) if observed_scores else 0.0, 6),
        },
        "profiles": profile_results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate critical-header short-code candidates")
    parser.add_argument("--module-grid", required=True, help="grid like 240x144")
    parser.add_argument("--mask-id", type=int, default=3, help="assumed mask id")
    parser.add_argument("--sender-frame", required=True, help="sender frame path")
    parser.add_argument("--captured-frame", required=True, help="captured frame path")
    parser.add_argument("--output-json", default=None, help="optional output json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    grid_w, grid_h = [int(part) for part in str(args.module_grid).lower().split("x", 1)]
    result = evaluate_pair(
        sender_frame=Path(args.sender_frame),
        captured_frame=Path(args.captured_frame),
        grid_w=grid_w,
        grid_h=grid_h,
        mask_id=int(args.mask_id),
    )
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
