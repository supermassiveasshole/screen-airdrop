#!/usr/bin/env python3
"""Compare candidate single-frame header codes under a simple binary error channel."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def _bits_from_bytes(data: bytes) -> list[int]:
    bits: list[int] = []
    for byte in data:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    return bits


def _bytes_from_bits(bits: list[int]) -> bytes:
    out = bytearray()
    for i in range(0, len(bits), 8):
        value = 0
        for bit in bits[i : i + 8]:
            value = (value << 1) | (bit & 1)
        out.append(value)
    return bytes(out)


def _random_bits(rng: random.Random, n: int) -> list[int]:
    return [rng.getrandbits(1) for _ in range(n)]


def _apply_bsc(bits: list[int], flip_probability: float, rng: random.Random) -> list[int]:
    out: list[int] = []
    for bit in bits:
        if rng.random() < flip_probability:
            out.append(bit ^ 1)
        else:
            out.append(bit)
    return out


def _encode_repetition(bits: list[int], rep: int) -> list[int]:
    encoded: list[int] = []
    for bit in bits:
        encoded.extend([bit] * rep)
    return encoded


def _decode_repetition(bits: list[int], rep: int) -> list[int]:
    decoded: list[int] = []
    for i in range(0, len(bits), rep):
        chunk = bits[i : i + rep]
        ones = sum(chunk)
        decoded.append(1 if ones * 2 >= len(chunk) else 0)
    return decoded


def _encode_hamming74(bits: list[int]) -> list[int]:
    padded = list(bits)
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


def _decode_hamming74(bits: list[int], message_bits: int) -> list[int]:
    decoded: list[int] = []
    for i in range(0, len(bits), 7):
        block = list(bits[i : i + 7])
        if len(block) < 7:
            break
        s1 = block[0] ^ block[2] ^ block[4] ^ block[6]
        s2 = block[1] ^ block[2] ^ block[5] ^ block[6]
        s3 = block[3] ^ block[4] ^ block[5] ^ block[6]
        syndrome = s1 | (s2 << 1) | (s3 << 2)
        if syndrome:
            err_index = syndrome - 1
            if 0 <= err_index < 7:
                block[err_index] ^= 1
        decoded.extend([block[2], block[4], block[5], block[6]])
    return decoded[:message_bits]


def _encode_secded84(bits: list[int]) -> list[int]:
    padded = list(bits)
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


def _decode_secded84(bits: list[int], message_bits: int) -> list[int]:
    decoded: list[int] = []
    for i in range(0, len(bits), 8):
        block = list(bits[i : i + 8])
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
            err_index = syndrome
            if err_index == 0:
                block[0] ^= 1
            elif 1 <= err_index <= 7:
                block[err_index] ^= 1
        decoded.extend([block[3], block[5], block[6], block[7]])
    return decoded[:message_bits]


def _candidate_table(message_bits: int) -> list[dict[str, object]]:
    return [
        {
            "name": "repetition_1",
            "encode": lambda bits: _encode_repetition(bits, 1),
            "decode": lambda bits: _decode_repetition(bits, 1)[:message_bits],
        },
        {
            "name": "repetition_2",
            "encode": lambda bits: _encode_repetition(bits, 2),
            "decode": lambda bits: _decode_repetition(bits, 2)[:message_bits],
        },
        {
            "name": "hamming74",
            "encode": _encode_hamming74,
            "decode": lambda bits: _decode_hamming74(bits, message_bits),
        },
        {
            "name": "secded84",
            "encode": _encode_secded84,
            "decode": lambda bits: _decode_secded84(bits, message_bits),
        },
    ]


def compare_codes(
    *,
    message_bits: int,
    flip_probabilities: list[float],
    trials: int,
    seed: int,
) -> dict[str, object]:
    rng = random.Random(seed)
    candidates = _candidate_table(message_bits)
    summary: dict[str, object] = {
        "message_bits": int(message_bits),
        "trials": int(trials),
        "seed": int(seed),
        "flip_probabilities": flip_probabilities,
        "candidates": [],
    }

    for candidate in candidates:
        encoded_bits = candidate["encode"]([0] * message_bits)
        rates: list[dict[str, float]] = []
        for flip_probability in flip_probabilities:
            successes = 0
            for _ in range(trials):
                message = _random_bits(rng, message_bits)
                encoded = candidate["encode"](message)
                corrupted = _apply_bsc(encoded, flip_probability, rng)
                decoded = candidate["decode"](corrupted)
                if decoded[:message_bits] == message[:message_bits]:
                    successes += 1
            rates.append(
                {
                    "flip_probability": float(flip_probability),
                    "success_rate": round(successes / float(trials), 6),
                }
            )
        summary["candidates"].append(
            {
                "name": candidate["name"],
                "code_bits": int(len(encoded_bits)),
                "rate": round(message_bits / float(len(encoded_bits)), 6),
                "results": rates,
            }
        )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare header code candidates")
    parser.add_argument("--message-bits", type=int, default=128, help="message bits to protect")
    parser.add_argument("--trials", type=int, default=2000, help="trials per candidate/probability")
    parser.add_argument("--seed", type=int, default=1234, help="random seed")
    parser.add_argument(
        "--flip-probabilities",
        default="0.01,0.02,0.03,0.04,0.05,0.06",
        help="comma-separated BSC flip probabilities",
    )
    parser.add_argument("--output-json", default=None, help="optional output json path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    flip_probabilities = [
        float(item) for item in str(args.flip_probabilities).split(",") if item.strip()
    ]
    summary = compare_codes(
        message_bits=int(args.message_bits),
        flip_probabilities=flip_probabilities,
        trials=int(args.trials),
        seed=int(args.seed),
    )
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
