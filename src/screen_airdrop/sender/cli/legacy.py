"""Python 3.7-compatible sender CLI entrypoint."""

from __future__ import annotations

import argparse
import sys

from screen_airdrop.sender.application.controller import run_sender
from screen_airdrop.sender.scheduling.broadcast_schedule import BroadcastSchedule


def build_parser():
    parser = argparse.ArgumentParser(description="screen-airdrop legacy sender (py3.7)")
    parser.add_argument("input_path")
    parser.add_argument("--fps", type=int, default=12, help="frames per second")
    parser.add_argument(
        "--chunk-fill-ratio",
        type=float,
        default=0.9,
        help="target chunk fill as a fraction of frame capacity (0.05-1.0)",
    )
    parser.add_argument(
        "--compress", choices=["gzip", "none"], default="gzip", help="compression method"
    )
    parser.add_argument(
        "--ecc-level",
        choices=["L", "M", "Q", "H"],
        default="Q",
        help="error correction level (affects robustness)",
    )
    parser.add_argument(
        "--module-grid", default="160x96", help="module grid size (affects frame capacity)"
    )
    parser.add_argument("--window-name", default="screen-airdrop", help="sender window title")
    parser.add_argument("--frame-width", type=int, default=1920, help="rendered frame width in pixels")
    parser.add_argument("--frame-height", type=int, default=1080, help="rendered frame height in pixels")
    parser.add_argument(
        "--manifest-repeat",
        type=int,
        default=5,
        help="repeat the manifest chunk this many times at the start of each epoch",
    )
    parser.add_argument(
        "--max-epochs", type=int, default=0, help="max transmission epochs (0=unlimited)"
    )
    parser.add_argument("--dump-frames", default=None, help="directory to dump frame images")
    parser.add_argument(
        "--dump-only",
        action="store_true",
        help="dump encoded frames without opening the sender window",
    )
    parser.add_argument("--report-json", default=None, help="path to write JSON report")
    parser.add_argument(
        "--overlay", action="store_true", help="show debug text overlay on sender window"
    )
    parser.add_argument(
        "--protocol",
        choices=["basic", "compact", "gray4", "layered"],
        default="basic",
        help="protocol name",
    )
    parser.add_argument(
        "--stats-interval", type=float, default=1.0, help="stats update interval in seconds"
    )
    parser.add_argument(
        "--emit-coded-units",
        action="store_true",
        help="emit coded erasure units after systematic units",
    )
    parser.add_argument(
        "--coded-redundancy-count",
        type=int,
        default=0,
        help="coded units to emit per generation",
    )
    parser.add_argument(
        "--coded-degree",
        type=int,
        default=2,
        help="GF(2^8) coded degree for coded units",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    guard_band_modules = 1 if args.protocol in ("compact", "gray4", "layered") else 2
    corner_size_modules = 7 if args.protocol in ("compact", "gray4", "layered") else 9
    schedule = BroadcastSchedule(
        sync_frames=4 if args.protocol == "layered" else 8,
        control_burst_repeat=args.manifest_repeat,
    )
    return run_sender(
        input_path=args.input_path,
        block_size=6,  # Hardcoded default
        chunk_size=None,
        chunk_fill_ratio=args.chunk_fill_ratio,
        fps=args.fps,
        compress=args.compress,
        sync_frames=schedule.sync_frames,
        manifest_repeat=schedule.control_burst_repeat,
        max_epochs=args.max_epochs,
        window_name=args.window_name,
        dump_frames=args.dump_frames,
        dump_only=args.dump_only,
        report_json=args.report_json,
        overlay=args.overlay,
        protocol=args.protocol,
        quiet_zone_px=48,  # Hardcoded default
        ecc_level=args.ecc_level,
        module_grid=args.module_grid,
        guard_band_modules=guard_band_modules,
        corner_size_modules=corner_size_modules,
        outer_padding_px=0,  # Hardcoded default
        outer_padding_color="black",  # Hardcoded default (removed confusing white option)
        stats_interval=args.stats_interval,
        width=args.frame_width,
        height=args.frame_height,
        schedule=schedule,
        emit_coded_units=bool(args.emit_coded_units),
        coded_redundancy_count=int(args.coded_redundancy_count),
        coded_degree=int(args.coded_degree),
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
