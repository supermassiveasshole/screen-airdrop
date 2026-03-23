"""Modern sender CLI entrypoint for Python 3.12+."""

from __future__ import annotations

import argparse
import sys

from screen_airdrop.sender.application.controller import run_sender
from screen_airdrop.sender.scheduling.broadcast_schedule import BroadcastSchedule


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="screen-airdrop modern sender (py3.12+)")
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
        default=None,  # Will be set based on protocol
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
        default=None,
        help="repeat the manifest chunk this many times at the start of each epoch",
    )
    parser.add_argument(
        "--data-realizations",
        type=int,
        default=None,
        help="send each data chunk this many distinct times per epoch",
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
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    # Set protocol-specific defaults
    if args.protocol == "compact":
        guard_band_modules = 1
        corner_size_modules = 7
        default_ecc = "Q"
    elif args.protocol == "gray4":
        guard_band_modules = 1
        corner_size_modules = 7
        default_ecc = "L"
    elif args.protocol == "layered":
        guard_band_modules = 1
        corner_size_modules = 7
        default_ecc = "L"
    else:  # basic
        guard_band_modules = 2
        corner_size_modules = 9
        default_ecc = "Q"
    default_manifest_repeat = (
        8 if args.protocol == "gray4" else (4 if args.protocol == "layered" else 5)
    )

    # Use user-specified ECC level or protocol default
    ecc_level = args.ecc_level if args.ecc_level is not None else default_ecc
    manifest_repeat = (
        int(args.manifest_repeat) if args.manifest_repeat is not None else default_manifest_repeat
    )
    data_realizations = int(args.data_realizations) if args.data_realizations is not None else 1
    schedule = BroadcastSchedule(
        sync_frames=4 if args.protocol == "layered" else 8,
        control_burst_repeat=manifest_repeat,
        data_realizations=data_realizations,
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
        ecc_level=ecc_level,
        module_grid=args.module_grid,
        guard_band_modules=guard_band_modules,
        corner_size_modules=corner_size_modules,
        outer_padding_px=0,  # Hardcoded default
        outer_padding_color="black",  # Keep sender canvas consistent across protocols
        stats_interval=args.stats_interval,
        width=args.frame_width,
        height=args.frame_height,
        schedule=schedule,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
