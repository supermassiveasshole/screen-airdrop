#!/usr/bin/env python3
"""End-to-end benchmark entrypoint.

Replay mode is fully automated.
Screen mode is semi-automated: it emits a runbook with strict commands.
"""

from __future__ import annotations

import argparse
import json
import math
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np

try:
    from benchmark_common import (
        ECC_LEVELS,
        LAYOUT_MODES,
        PAYLOAD_MODES,
        ProtocolConfig,
        make_encoder,
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
        ProtocolConfig,
        make_encoder,
        payload_size_for_mode,
        protocol_config_dict,
        protocol_configs,
        write_json_result,
    )

from screen_airdrop.receiver.cli import main as receiver_main
from screen_airdrop.sender.controller import build_encoded_frames

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="End-to-end benchmark for basic vs compact.")
    parser.add_argument("--mode", choices=["replay", "screen"], default="screen")
    parser.add_argument("--protocol", choices=["basic", "compact", "all"], default="all")
    parser.add_argument("--layout-mode", choices=list(LAYOUT_MODES), default="same_grid")
    parser.add_argument("--ecc", choices=["all", *ECC_LEVELS], default="Q")
    parser.add_argument("--payload-mode", choices=list(PAYLOAD_MODES), default="fixed")
    parser.add_argument("--payload-size", type=int, default=500)
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--module-grid", type=str, default="160x96")
    parser.add_argument("--capture-fps", type=int, default=30)
    parser.add_argument("--stats-interval", type=float, default=1.0)
    parser.add_argument("--benchmark-seconds", type=int, default=30)
    parser.add_argument(
        "--input",
        type=str,
        default=str(ROOT / "tests" / "fixtures" / "real_data" / "regular_pdf"),
    )
    parser.add_argument("--output-json", type=str, default="")
    return parser.parse_args()


def _protocol_chunk_size(config: ProtocolConfig, ecc_level: str, payload_mode: str, payload_size: int) -> int:
    layout = make_encoder(config, ecc_level).get_layout()
    return payload_size_for_mode(layout, payload_mode, payload_size)


def _run_replay_case(
    config: ProtocolConfig,
    layout_mode: str,
    ecc_level: str,
    payload_mode: str,
    payload_size: int,
    fps: int,
    stats_interval: float,
    benchmark_seconds: int,
    input_path: str,
    frame_width: int = 1920,
    frame_height: int = 1080,
) -> dict[str, Any]:
    chunk_size = _protocol_chunk_size(config, ecc_level, payload_mode, payload_size)
    with tempfile.TemporaryDirectory(prefix="sa-e2e-") as td:
        tmp = Path(td)
        frame_dir = tmp / "frames"
        frame_dir.mkdir()
        out_dir = tmp / "out"
        report_path = tmp / "report.json"

        one_epoch = list(
            build_encoded_frames(
                input_path=input_path,
                chunk_size=chunk_size,
                sync_frames=10,
                epochs=1,
                width=frame_width,
                height=frame_height,
                protocol=config.protocol,
                module_grid=f"{config.grid_w}x{config.grid_h}",
                ecc_level=ecc_level,
            )
        )
        metadata = next(item["metadata"] for item in one_epoch if "metadata" in item)
        target_frames = max(1, int(math.ceil(fps * benchmark_seconds)) + 10)
        epochs = max(1, int(math.ceil(target_frames / max(1, len(one_epoch)))))
        encoded = list(
            build_encoded_frames(
                input_path=input_path,
                chunk_size=chunk_size,
                sync_frames=10,
                epochs=epochs,
                width=frame_width,
                height=frame_height,
                protocol=config.protocol,
                module_grid=f"{config.grid_w}x{config.grid_h}",
                ecc_level=ecc_level,
            )
        )
        for i, item in enumerate(encoded):
            np.save(frame_dir / f"{i:06d}.npy", item["image"])

        started = time.time()
        code = receiver_main(
            [
                "--source",
                "replay",
                "--frames-dir",
                str(frame_dir),
                "--output-dir",
                str(out_dir),
                "--protocol",
                config.protocol,
                "--module-grid",
                f"{config.grid_w}x{config.grid_h}",
                "--stats-interval",
                str(stats_interval),
                "--max-seconds",
                str(benchmark_seconds),
                "--report-json",
                str(report_path),
            ]
        )
        elapsed = max(1e-6, time.time() - started)
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        report.update(
            {
                "benchmark_kind": "end_to_end_replay",
                "protocol": config.protocol,
                "config": protocol_config_dict(config),
                "layout_mode": layout_mode,
                "ecc_level": ecc_level,
                "payload_mode": payload_mode,
                "payload_bytes": chunk_size,
                "fps": fps,
                "benchmark_seconds": benchmark_seconds,
                "frame_width": frame_width,
                "frame_height": frame_height,
                "stats_interval": stats_interval,
                "benchmark_goal": "rate_only",
                "completed_transfer": bool(report.get("status") == "ok"),
                "tx_payload_kib_per_s": float(chunk_size * fps / 1024.0),
                "rx_payload_kib_per_s": float(report.get("goodput_kibps", report.get("goodput_kbps", 0.0))),
                "benchmark_elapsed_s": elapsed,
                "exit_code": code,
                "frame_payload_cap": metadata.get("frame_payload_cap", 0),
                "effective_chunk_size": metadata.get("effective_chunk_size", chunk_size),
                "epochs_rendered": epochs,
            }
        )
        return report


def _screen_runbook_case(
    config: ProtocolConfig,
    layout_mode: str,
    ecc_level: str,
    payload_mode: str,
    payload_size: int,
    fps: int,
    capture_fps: int,
    benchmark_seconds: int,
    stats_interval: float,
    input_path: str,
    frame_width: int = 1920,
    frame_height: int = 1080,
) -> dict[str, Any]:
    chunk_size = _protocol_chunk_size(config, ecc_level, payload_mode, payload_size)
    frame_size_args = ""
    if (frame_width, frame_height) != (1920, 1080):
        frame_size_args = f" --frame-width {frame_width} --frame-height {frame_height}"
    return {
        "benchmark_kind": "end_to_end_screen_runbook",
        "protocol": config.protocol,
        "config": protocol_config_dict(config),
        "layout_mode": layout_mode,
        "ecc_level": ecc_level,
        "payload_mode": payload_mode,
        "payload_bytes": chunk_size,
        "fps": fps,
        "capture_fps": capture_fps,
        "benchmark_seconds": benchmark_seconds,
        "frame_width": frame_width,
        "frame_height": frame_height,
        "stats_interval": stats_interval,
        "benchmark_goal": "rate_only",
        "sender_command": (
            f"uv run screen-airdrop-sender {input_path} --protocol {config.protocol} "
            f"--module-grid {config.grid_w}x{config.grid_h} --ecc-level {ecc_level} "
            f"--fps {fps} --chunk-size {chunk_size}{frame_size_args} --stats-interval {stats_interval}"
        ),
        "receiver_command": (
            f"uv run screen-airdrop-receiver --source screen --protocol {config.protocol} "
            f"--module-grid {config.grid_w}x{config.grid_h} --roi-interactive "
            f"--capture-fps {capture_fps} --stats-interval {stats_interval} "
            f"--max-seconds {benchmark_seconds} "
            f"--output-dir ./recovered_{config.protocol}_{ecc_level}_{payload_mode}"
        ),
    }


def main() -> int:
    args = parse_args()
    ecc_levels = list(ECC_LEVELS) if args.ecc == "all" else [args.ecc]
    configs = protocol_configs(args.protocol, args.layout_mode)

    results = []
    for config in configs:
        for ecc_level in ecc_levels:
            if args.mode == "replay":
                result = _run_replay_case(
                    config=config,
                    layout_mode=args.layout_mode,
                    ecc_level=ecc_level,
                    payload_mode=args.payload_mode,
                    payload_size=args.payload_size,
                    fps=args.fps,
                    benchmark_seconds=args.benchmark_seconds,
                    stats_interval=args.stats_interval,
                    input_path=args.input,
                )
            else:
                result = _screen_runbook_case(
                    config=config,
                    layout_mode=args.layout_mode,
                    ecc_level=ecc_level,
                    payload_mode=args.payload_mode,
                    payload_size=args.payload_size,
                    fps=args.fps,
                    capture_fps=args.capture_fps,
                    benchmark_seconds=args.benchmark_seconds,
                    stats_interval=args.stats_interval,
                    input_path=args.input,
                )
            results.append(result)
            print(json.dumps(result, ensure_ascii=False))

    out_path = write_json_result(f"end_to_end_{args.mode}_benchmark", results)
    if args.output_json:
        Path(args.output_json).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Saved:", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
