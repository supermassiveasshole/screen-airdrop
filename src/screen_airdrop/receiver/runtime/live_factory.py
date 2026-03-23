"""Factory helpers for live receiver runtime."""

from __future__ import annotations

from typing import Optional, Tuple

from screen_airdrop.receiver.config import ReceiverConfig
from screen_airdrop.receiver.information import ChunkAssembler
from screen_airdrop.receiver.pipeline.live import ScreenLiveRuntime
from screen_airdrop.receiver.runtime.screen_capture import ScreenCapture


def create_live_pipeline(
    *,
    config: ReceiverConfig,
    source: ScreenCapture,
    assembler: ChunkAssembler,
    forced_roi_local: Optional[Tuple[int, int, int, int]],
    guard_band: int,
    corner_size: int,
    grid_w: int,
    grid_h: int,
) -> ScreenLiveRuntime:
    manual_mode = forced_roi_local is not None
    return ScreenLiveRuntime(
        capture=source,
        assembler=assembler,
        decode_workers=config.decode_workers,
        prep_process=config.prep_process,
        frame_queue_size=config.frame_queue_size,
        result_queue_size=config.result_queue_size,
        capture_fps=config.capture_fps,
        capture_dump_dir=config.capture_dump_dir,
        capture_dump_max_frames=config.capture_dump_max_frames,
        debug_dir=config.debug_dir,
        debug_interval=config.debug_interval,
        debug_max_frames=config.debug_max_frames,
        protocol=config.protocol,
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=guard_band,
        corner_size=corner_size,
        manual_mode=manual_mode,
        initial_search_roi=forced_roi_local,
    )
