# pyright: reportArgumentType=false, reportOperatorIssue=false
"""Realtime/replay receiver CLI with V2 auto locator and manual ROI fallback."""

from __future__ import annotations

import argparse
import contextlib
import os
import signal
import sys

from screen_airdrop.receiver.assembler import ChunkAssembler
from screen_airdrop.receiver.capture_mss import ScreenCapture
from screen_airdrop.receiver.config import ReceiverConfig
from screen_airdrop.receiver.frame_replay_source import FrameReplaySource
from screen_airdrop.receiver.pipeline_factory import create_pipeline
from screen_airdrop.receiver.reporter_factory import create_progress_reporter
from screen_airdrop.receiver.roi_policy import RoiPolicy
from screen_airdrop.receiver.roi_setup import setup_roi
from screen_airdrop.receiver.runtime.pipeline_runner import PipelineRunner
from screen_airdrop.receiver.stats import TransferStats


def _build_source(config: ReceiverConfig, capture_region):
    if config.is_replay_mode():
        if not config.frames_dir:
            raise ValueError("--frames-dir is required when --source replay")
        return FrameReplaySource(frames_dir=config.frames_dir)

    return ScreenCapture(
        window_title=config.window_title,
        region=capture_region,
        monitor_index=config.monitor_index,
    )


def _select_capture_region(roi_policy: RoiPolicy, forced_roi):
    del roi_policy
    return forced_roi


def _warn_window_title_fallback(config: ReceiverConfig) -> None:
    if config.source != "screen" or not config.window_title:
        return
    if config.roi:
        return
    print(
        "warning: --window-title is currently not used for real window lookup; "
        "capture will fallback to full monitor. "
        "Use --roi x,y,w,h or --roi-interactive for reliable decode."
    )


def _configure_debug_capture(config: ReceiverConfig, source) -> None:
    if config.debug_dir and isinstance(source, ScreenCapture):
        source.frame_diff_threshold = 0.0

    if not config.debug_dir:
        return

    os.makedirs(config.debug_dir, exist_ok=True)
    print(
        f"debug enabled: dir={config.debug_dir} interval={config.debug_interval}s "
        f"max_frames={config.debug_max_frames}"
    )


def _print_pipeline_banner(config: ReceiverConfig, forced_roi) -> None:
    if config.is_replay_mode():
        print(
            f"replay pipeline: protocol={config.protocol} "
            f"frames_dir={config.frames_dir}"
        )
        return

    print(
        f"screen live runtime: protocol={config.protocol} workers={config.decode_workers} "
        f"prep={config.prep_process} capture_fps={config.capture_fps} "
        f"mode={'manual' if forced_roi else 'auto'}"
    )


@contextlib.contextmanager
def _pipeline_signal_guard(pipeline):
    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    shutting_down = False

    def _handle_shutdown_signal(signum, frame):
        del signum, frame
        nonlocal shutting_down
        if not shutting_down:
            shutting_down = True
            with contextlib.suppress(Exception):
                pipeline.stop()
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="screen-airdrop receiver")
    # Source configuration
    parser.add_argument(
        "--source", choices=["screen", "replay"], default="screen", help="capture source"
    )
    parser.add_argument(
        "--window-title", default=None, help="window title to locate (screen source)"
    )
    parser.add_argument("--monitor-index", type=int, default=1, help="mss monitor index (1-based)")
    parser.add_argument(
        "--frames-dir", default=None, help="directory with captured frames (replay source)"
    )
    parser.add_argument(
        "--replay-geometry-mode",
        choices=["stateful", "stateless"],
        default="stateful",
        help=argparse.SUPPRESS,
    )

    # Protocol and grid configuration
    parser.add_argument(
        "--protocol",
        choices=["basic", "compact", "gray4", "layered"],
        default="basic",
        help="protocol name",
    )
    parser.add_argument(
        "--module-grid", default="160x96", help="module grid size (must match sender)"
    )
    parser.add_argument(
        "--block-size",
        default="6",
        help="legacy compatibility option; ignored by the basic protocol decoder",
    )

    # ROI configuration
    parser.add_argument(
        "--roi", default=None, help="manual ROI as x,y,w,h (if not set, use auto detection)"
    )
    parser.add_argument(
        "--roi-interactive", action="store_true", help="enable interactive ROI selection"
    )

    # Output configuration
    parser.add_argument(
        "--output-dir", default="./recovered", help="output directory for recovered files"
    )
    parser.add_argument("--report-json", default=None, help="path to write JSON report")

    # Timing configuration
    parser.add_argument(
        "--max-idle-seconds", type=int, default=30, help="max idle time before exit"
    )
    parser.add_argument("--max-seconds", type=int, default=0, help="max total time (0=unlimited)")
    parser.add_argument(
        "--stats-interval", type=float, default=1.0, help="stats update interval in seconds"
    )
    parser.add_argument(
        "--capture-fps",
        type=float,
        default=30.0,
        help="target capture FPS (screen source only)",
    )

    # Debug configuration
    parser.add_argument("--debug-dir", default=None, help="dump debug snapshots to this directory")
    parser.add_argument(
        "--debug-interval", type=float, default=1.0, help="seconds between debug snapshots"
    )
    parser.add_argument(
        "--debug-max-frames", type=int, default=30, help="max debug snapshots to write"
    )

    # Advanced configuration
    parser.add_argument(
        "--decode-workers",
        type=int,
        default=1,
        help="number of parallel decode workers",
    )
    parser.add_argument(
        "--prep-process",
        type=int,
        default=0,
        help="screen live runtime prep mode: 0=async in coordinator, 1=dedicated prep process",
    )
    parser.add_argument(
        "--frame-queue-size",
        type=int,
        default=32,
        help="pipeline frame queue size (screen source only)",
    )
    parser.add_argument(
        "--result-queue-size",
        type=int,
        default=256,
        help="pipeline result queue size (screen source only)",
    )
    parser.add_argument(
        "--capture-dump-dir",
        default=None,
        help="dump pipeline-captured frames for later replay (screen source only)",
    )
    parser.add_argument(
        "--capture-dump-max-frames",
        type=int,
        default=0,
        help="max pipeline-captured frames to dump (0=disabled)",
    )
    return parser


def main(argv=None):
    """Simplified main function using factory modules."""
    args = build_parser().parse_args(argv)
    config = ReceiverConfig.from_args(args)
    config.validate()
    roi_policy = RoiPolicy.from_args(args)

    _warn_window_title_fallback(config)

    assembler = ChunkAssembler()
    stats = TransferStats()
    forced_roi = setup_roi(config, roi_policy, stats)
    capture_region = _select_capture_region(roi_policy, forced_roi)
    source = _build_source(config, capture_region)
    _configure_debug_capture(config, source)
    pipeline = create_pipeline(config, source, assembler, forced_roi)
    _print_pipeline_banner(config, forced_roi)
    progress_reporter = create_progress_reporter(config.source)
    runner = PipelineRunner(
        pipeline=pipeline,
        assembler=assembler,
        max_seconds=config.max_seconds,
        max_idle_seconds=config.max_idle_seconds,
        stats_interval=config.stats_interval,
        output_dir=config.output_dir,
        progress_reporter=progress_reporter,
    )

    with _pipeline_signal_guard(pipeline):
        exit_code, report = runner.run()

    report.dump(config.report_json)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
