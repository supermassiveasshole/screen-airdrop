"""Python 3.7-compatible sender CLI entrypoint."""

from __future__ import annotations

import argparse
import sys

from .controller import run_sender


def build_parser():
    parser = argparse.ArgumentParser(description="screen-airdrop legacy sender (py3.7)")
    parser.add_argument("input_path")
    parser.add_argument("--fps", type=int, default=12, help="frames per second")
    parser.add_argument(
        "--chunk-size", type=int, default=2048, help="chunk size in bytes (affects data capacity)"
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
        "--max-epochs", type=int, default=0, help="max transmission epochs (0=unlimited)"
    )
    parser.add_argument("--dump-frames", default=None, help="directory to dump frame images")
    parser.add_argument("--report-json", default=None, help="path to write JSON report")
    parser.add_argument(
        "--overlay", action="store_true", help="show debug text overlay on sender window"
    )
    parser.add_argument(
        "--protocol",
        choices=["basic", "compact"],
        default="basic",
        help="protocol name",
    )
    parser.add_argument(
        "--stats-interval", type=float, default=1.0, help="stats update interval in seconds"
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    guard_band_modules = 1 if args.protocol == "compact" else 2
    corner_size_modules = 7 if args.protocol == "compact" else 9
    return run_sender(
        input_path=args.input_path,
        block_size=6,  # Hardcoded default
        chunk_size=args.chunk_size,
        fps=args.fps,
        compress=args.compress,
        sync_frames=30,  # Hardcoded default
        manifest_repeat=5,  # Hardcoded default
        max_epochs=args.max_epochs,
        window_name=args.window_name,
        dump_frames=args.dump_frames,
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
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
