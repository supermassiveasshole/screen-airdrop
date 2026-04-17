"""Factory helpers for simulated live receiver runtime."""

from __future__ import annotations

from screen_airdrop.receiver.application.replay_source import FrameReplaySource
from screen_airdrop.receiver.config import ReceiverConfig
from screen_airdrop.receiver.information import ChunkAssembler
from screen_airdrop.receiver.pipeline.simulated_live import SimulatedLiveRuntime


def create_simulated_live_pipeline(
    *,
    config: ReceiverConfig,
    source: FrameReplaySource,
    assembler: ChunkAssembler,
    forced_roi_local,
    guard_band: int,
    corner_size: int,
    grid_w: int,
    grid_h: int,
) -> SimulatedLiveRuntime:
    del forced_roi_local
    return SimulatedLiveRuntime(
        frame_source=source,
        assembler=assembler,
        decode_workers=config.decode_workers,
        prep_process=config.prep_process,
        frame_queue_size=config.frame_queue_size,
        result_queue_size=config.result_queue_size,
        capture_fps=config.capture_fps,
        debug_dir=config.debug_dir,
        debug_interval=config.debug_interval,
        debug_max_frames=config.debug_max_frames,
        protocol=config.protocol,
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=guard_band,
        corner_size=corner_size,
        pacing_mode=config.simulated_live_pacing,
    )
