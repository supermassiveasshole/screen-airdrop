"""Factory for creating pipeline instances."""

from typing import Optional, Tuple, Union

from screen_airdrop.receiver.assembler import ChunkAssembler
from screen_airdrop.receiver.capture_mss import ScreenCapture, get_monitor_region
from screen_airdrop.receiver.config import ReceiverConfig
from screen_airdrop.receiver.frame_replay_source import FrameReplaySource
from screen_airdrop.receiver.protocol_config import get_protocol_geometry
from screen_airdrop.receiver.roi import RoiManager
from screen_airdrop.receiver.runtime.base_pipeline import BasePipeline
from screen_airdrop.receiver.runtime.replay_pipeline import ReplayPipeline
from screen_airdrop.receiver.screen_live_runtime import ScreenLiveRuntime
from screen_airdrop.receiver.window_locator import resolve_window_region


def create_pipeline(
    config: ReceiverConfig,
    source: Union[ScreenCapture, FrameReplaySource],
    assembler: ChunkAssembler,
    forced_roi: Optional[Tuple[int, int, int, int]],
) -> BasePipeline:
    """Create pipeline based on config and source type.

    Args:
        config: Receiver configuration
        source: Frame source (ScreenCapture or FrameReplaySource)
        assembler: Chunk assembler
        forced_roi: Forced ROI in absolute coordinates (or None)

    Returns:
        ReplayPipeline or ScreenLiveRuntime instance
    """
    # Get protocol geometry
    guard_band, corner_size = get_protocol_geometry(config.protocol)

    # Get grid size
    grid_w, grid_h = config.get_grid_size()

    if config.is_replay_mode():
        # Replay mode: use simple ReplayPipeline
        return ReplayPipeline(
            frame_source=source,
            assembler=assembler,
            protocol=config.protocol,
            grid_w=grid_w,
            grid_h=grid_h,
            guard_band=guard_band,
            corner_size=corner_size,
        )
    else:
        # Screen mode: use ScreenLiveRuntime
        # Convert absolute ROI to local coordinates if needed
        pipeline_seed_roi_local = _build_pipeline_seed_roi_local(source, forced_roi)
        manual_mode = forced_roi is not None

        return ScreenLiveRuntime(
            capture=source,
            assembler=assembler,
            decode_workers=config.decode_workers,
            prep_process=config.prep_process,
            capture_fps=config.capture_fps,
            capture_dump_dir=config.capture_dump_dir,
            capture_dump_max_frames=config.capture_dump_max_frames,
            protocol=config.protocol,
            grid_w=grid_w,
            grid_h=grid_h,
            guard_band=guard_band,
            corner_size=corner_size,
            manual_mode=manual_mode,
            initial_search_roi=pipeline_seed_roi_local,
        )


def _build_pipeline_seed_roi_local(
    source: Union[ScreenCapture, FrameReplaySource],
    forced_roi_abs: Optional[Tuple[int, int, int, int]],
) -> Optional[Tuple[int, int, int, int]]:
    """Convert absolute ROI to local frame coordinates.

    Args:
        source: Frame source (must be ScreenCapture for conversion)
        forced_roi_abs: Forced ROI in absolute screen coordinates

    Returns:
        ROI in local frame coordinates, or None if conversion fails
    """
    if forced_roi_abs is None:
        return None

    try:
        monitor_index = int(getattr(source, "monitor_index"))
        window_title = getattr(source, "window_title")
        explicit_region = getattr(source, "region")
        monitor_region = get_monitor_region(monitor_index)

        capture_region = resolve_window_region(
            window_title=window_title,
            explicit_region=explicit_region,
            monitor_region=monitor_region,
        )
        frame_shape = (int(capture_region[3]), int(capture_region[2]), 3)
        roi_mgr = RoiManager(capture_region)
        return roi_mgr.abs_to_local(forced_roi_abs, frame_shape)
    except Exception:
        return None
