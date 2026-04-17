"""Factory helpers for replay receiver runtime."""

from screen_airdrop.receiver.application.replay_source import FrameReplaySource
from screen_airdrop.receiver.config import ReceiverConfig
from screen_airdrop.receiver.information import ChunkAssembler
from screen_airdrop.receiver.pipeline.replay import ReplayPipeline


def create_replay_pipeline(
    *,
    config: ReceiverConfig,
    source: FrameReplaySource,
    assembler: ChunkAssembler,
    decode_workers: int,
    guard_band: int,
    corner_size: int,
    grid_w: int,
    grid_h: int,
) -> ReplayPipeline:
    return ReplayPipeline(
        frame_source=source,
        assembler=assembler,
        protocol=config.protocol,
        decode_workers=int(decode_workers),
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=guard_band,
        corner_size=corner_size,
        replay_geometry_mode=getattr(config, "replay_geometry_mode", "stateful"),
    )
