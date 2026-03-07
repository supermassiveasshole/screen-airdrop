"""Modern sender CLI entrypoint for Python 3.12+."""

from __future__ import annotations

import argparse
import sys

from .controller import run_sender


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="screen-airdrop modern sender (py3.12+)")
    parser.add_argument("input_path")
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--block-size", type=int, default=6, choices=[4, 6, 8])
    parser.add_argument("--chunk-size", type=int, default=2048)
    parser.add_argument("--compress", choices=["gzip", "none"], default="gzip")
    parser.add_argument("--sync-frames", type=int, default=30)
    parser.add_argument("--manifest-repeat", type=int, default=5)
    parser.add_argument("--max-epochs", type=int, default=0)
    parser.add_argument("--window-name", default="screen-airdrop")
    parser.add_argument("--dump-frames", default=None)
    parser.add_argument("--report-json", default=None)
    parser.add_argument("--overlay", action="store_true", help="show debug text overlay on sender window")
    parser.add_argument("--protocol", choices=["v3_1", "v3", "v2", "v1"], default="v3_1")
    parser.add_argument("--quiet-zone-px", type=int, default=48)
    parser.add_argument("--ecc-level", choices=["L", "M", "Q", "H"], default="Q")
    parser.add_argument("--module-grid", default="160x96")
    parser.add_argument("--guard-band-modules", type=int, default=2)
    parser.add_argument("--corner-size-modules", type=int, default=9)
    parser.add_argument("--outer-padding-px", type=int, default=0)
    parser.add_argument("--outer-padding-color", choices=["black", "white"], default="black")
    parser.add_argument("--stats-interval", type=float, default=1.0)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return run_sender(
        input_path=args.input_path,
        block_size=args.block_size,
        chunk_size=args.chunk_size,
        fps=args.fps,
        compress=args.compress,
        sync_frames=args.sync_frames,
        manifest_repeat=args.manifest_repeat,
        max_epochs=args.max_epochs,
        window_name=args.window_name,
        dump_frames=args.dump_frames,
        report_json=args.report_json,
        overlay=args.overlay,
        protocol=args.protocol,
        quiet_zone_px=args.quiet_zone_px,
        ecc_level=args.ecc_level,
        module_grid=args.module_grid,
        guard_band_modules=args.guard_band_modules,
        corner_size_modules=args.corner_size_modules,
        outer_padding_px=args.outer_padding_px,
        outer_padding_color=args.outer_padding_color,
        stats_interval=args.stats_interval,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
