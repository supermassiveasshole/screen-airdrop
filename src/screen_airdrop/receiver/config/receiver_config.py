"""Receiver configuration."""

import argparse
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class ReceiverConfig:
    """Configuration for screen-airdrop receiver.

    This class encapsulates all command-line arguments and derived configuration
    for the receiver, making it easier to pass configuration around and test.
    """

    # Source configuration
    source: str
    frames_dir: Optional[str]
    window_title: Optional[str]
    monitor_index: int

    # Protocol configuration
    protocol: str
    module_grid: str
    block_size: str

    # ROI configuration
    roi: Optional[str]
    region: Optional[str]
    roi_profile: Optional[str]
    roi_mode: str
    roi_interactive: bool

    # Decode configuration
    decode_workers: int
    prep_process: int
    detect_mode: str
    track_margin_px: int
    locator_confidence_threshold: float
    locator_engine: str

    # Capture configuration
    capture_fps: float
    capture_dump_dir: Optional[str]
    capture_dump_max_frames: int

    # Output configuration
    output_dir: str
    report_json: Optional[str]

    # Timing configuration
    max_seconds: int
    max_idle_seconds: int
    stats_interval: float

    # Debug configuration
    debug_dir: Optional[str]
    debug_interval: float
    debug_max_frames: int

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "ReceiverConfig":
        """Create configuration from argparse Namespace.

        Args:
            args: Parsed command-line arguments

        Returns:
            ReceiverConfig instance
        """
        return cls(
            # Source
            source=args.source,
            frames_dir=args.frames_dir,
            window_title=args.window_title,
            monitor_index=args.monitor_index,
            # Protocol
            protocol=args.protocol,
            module_grid=args.module_grid,
            block_size=args.block_size,
            # ROI
            roi=args.roi,
            region=args.region,
            roi_profile=args.roi_profile,
            roi_mode=args.roi_mode,
            roi_interactive=args.roi_interactive,
            # Decode
            decode_workers=args.decode_workers,
            prep_process=args.prep_process,
            detect_mode=args.detect_mode,
            track_margin_px=args.track_margin_px,
            locator_confidence_threshold=args.locator_confidence_threshold,
            locator_engine=args.locator_engine,
            # Capture
            capture_fps=args.capture_fps,
            capture_dump_dir=args.capture_dump_dir,
            capture_dump_max_frames=args.capture_dump_max_frames,
            # Output
            output_dir=args.output_dir,
            report_json=args.report_json,
            # Timing
            max_seconds=args.max_seconds,
            max_idle_seconds=args.max_idle_seconds,
            stats_interval=args.stats_interval,
            # Debug
            debug_dir=args.debug_dir,
            debug_interval=args.debug_interval,
            debug_max_frames=args.debug_max_frames,
        )

    def validate(self) -> None:
        """Validate configuration.

        Raises:
            ValueError: If configuration is invalid
        """
        if self.source == "replay" and not self.frames_dir:
            raise ValueError("replay source requires --frames-dir")

        if self.max_seconds < 0:
            raise ValueError("max-seconds must be non-negative")

        if self.max_idle_seconds < 0:
            raise ValueError("max-idle-seconds must be non-negative")

        if self.decode_workers < 0:
            raise ValueError("decode-workers must be non-negative")

    def is_replay_mode(self) -> bool:
        """Check if in replay mode."""
        return self.source == "replay"

    def is_screen_mode(self) -> bool:
        """Check if in screen capture mode."""
        return self.source == "screen"

    def has_debug(self) -> bool:
        """Check if debug mode is enabled."""
        return self.debug_dir is not None

    def get_grid_size(self) -> Tuple[int, int]:
        """Parse and return grid size.

        Returns:
            Tuple of (grid_w, grid_h)

        Raises:
            ValueError: If module_grid format is invalid
        """
        try:
            gw, gh = [int(p) for p in self.module_grid.lower().split("x")]
        except Exception as exc:
            raise ValueError(f"module-grid must be like 160x96: {exc}")
        if gw < 64 or gh < 48:
            raise ValueError("module-grid too small")
        return gw, gh

    def get_block_size_candidates(self) -> list[int]:
        """Get block size candidates for auto-detection.

        Returns:
            List of block sizes to try
        """
        if self.block_size == "auto":
            return [6, 8, 4]
        return [int(self.block_size)]
