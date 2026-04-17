#!/usr/bin/env python3
"""Synthetic encode/decode CPU microbenchmark for basic vs compact."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

import numpy as np

try:
    from benchmark_common import (
        ECC_LEVELS,
        LAYOUT_MODES,
        PAYLOAD_MODES,
        payload_bits_per_module,
        payload_size_for_mode,
        protocol_config_dict,
        protocol_configs,
        write_json_result,
    )
except ModuleNotFoundError:
    from bench.benchmark_common import (
        ECC_LEVELS,
        LAYOUT_MODES,
        PAYLOAD_MODES,
        payload_bits_per_module,
        payload_size_for_mode,
        protocol_config_dict,
        protocol_configs,
        write_json_result,
    )

from screen_airdrop.common.transport.protocol_basic import FRAME_DATA, FrameHeaderBasic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synthetic CPU microbenchmark for encode/decode only."
    )
    parser.add_argument("--protocol", choices=["basic", "compact", "gray4", "all"], default="all")
    parser.add_argument("--layout-mode", choices=list(LAYOUT_MODES), default="same_grid")
    parser.add_argument("--ecc", choices=["all", *ECC_LEVELS], default="Q")
    parser.add_argument("--payload-mode", choices=list(PAYLOAD_MODES), default="fixed")
    parser.add_argument("--payload-size", type=int, default=500)
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--output-json", type=str, default="")
    return parser.parse_args()


def benchmark_protocol(
    *,
    protocol_name: str,
    config,
    encoder,
    decoder,
    ecc_level: str,
    layout_mode: str,
    payload_mode: str,
    payload_size: int,
    iterations: int,
    width: int,
    height: int,
) -> dict[str, Any]:
    layout = encoder.get_layout()
    actual_payload_bytes = payload_size_for_mode(layout, payload_mode, payload_size)
    payload = b"X" * actual_payload_bytes

    encode_times = []
    frames = []
    for i in range(iterations):
        header = FrameHeaderBasic.make(
            frame_type=FRAME_DATA,
            session_id=1,
            epoch_id=0,
            frame_id=i,
            total_frames=iterations,
            chunk_id=i,
            payload=payload,
        )
        t0 = time.perf_counter()
        frame = encoder.encode_frame(header, payload, width, height)
        t1 = time.perf_counter()
        encode_times.append((t1 - t0) * 1000)
        frames.append(frame)

    decode_times = []
    decode_successes = 0
    for frame in frames:
        t0 = time.perf_counter()
        try:
            result = decoder.decode_frame(frame, detect_mode="full")
            t1 = time.perf_counter()
            decode_times.append((t1 - t0) * 1000)
            if result.payload == payload:
                decode_successes += 1
        except Exception:
            t1 = time.perf_counter()
            decode_times.append((t1 - t0) * 1000)

    avg_encode = float(np.mean(encode_times))
    avg_decode = float(np.mean(decode_times))
    total_ms = avg_encode + avg_decode
    synthetic_cpu_kib_per_s = float(len(payload) / (total_ms / 1000.0) / 1024.0)

    return {
        "benchmark_kind": "synthetic_cpu",
        "protocol": protocol_name,
        "config": protocol_config_dict(config),
        "layout_mode": layout_mode,
        "ecc_level": ecc_level,
        "payload_mode": payload_mode,
        "payload_bytes": len(payload),
        "payload_bits_per_module": payload_bits_per_module(layout, len(payload)),
        "capacity_bytes": layout.data_capacity_bits // 8,
        "frame_size_modules": [layout.frame_w, layout.frame_h],
        "finder_size": layout.finder_size,
        "guard_band": layout.guard_band,
        "iterations": iterations,
        "encode_ms": avg_encode,
        "decode_ms": avg_decode,
        "total_ms": total_ms,
        "success_rate": float(decode_successes) / float(iterations),
        "synthetic_cpu_kib_per_s": synthetic_cpu_kib_per_s,
    }


def main() -> int:
    try:
        from benchmark_common import make_decoder, make_encoder
    except ModuleNotFoundError:
        from bench.benchmark_common import make_decoder, make_encoder

    args = parse_args()
    ecc_levels = list(ECC_LEVELS) if args.ecc == "all" else [args.ecc]
    configs = protocol_configs(args.protocol, args.layout_mode)

    results = []
    for config in configs:
        for ecc_level in ecc_levels:
            encoder = make_encoder(config, ecc_level)
            decoder = make_decoder(config)
            result = benchmark_protocol(
                protocol_name=config.protocol,
                config=config,
                encoder=encoder,
                decoder=decoder,
                ecc_level=ecc_level,
                layout_mode=args.layout_mode,
                payload_mode=args.payload_mode,
                payload_size=args.payload_size,
                iterations=args.iterations,
                width=args.width,
                height=args.height,
            )
            results.append(result)
            print(
                json.dumps(
                    {
                        "protocol": result["protocol"],
                        "ecc": result["ecc_level"],
                        "layout_mode": result["layout_mode"],
                        "payload_mode": result["payload_mode"],
                        "payload_bytes": result["payload_bytes"],
                        "success_rate": result["success_rate"],
                        "encode_ms": round(result["encode_ms"], 2),
                        "decode_ms": round(result["decode_ms"], 2),
                        "synthetic_cpu_kib_per_s": round(result["synthetic_cpu_kib_per_s"], 2),
                    },
                    ensure_ascii=False,
                )
            )

    out_path = write_json_result("synthetic_cpu_benchmark", results)
    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
    print("Saved:", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
