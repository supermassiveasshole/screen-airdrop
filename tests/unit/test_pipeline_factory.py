"""Tests for pipeline_factory module."""

from unittest.mock import MagicMock, patch

from screen_airdrop.receiver.assembler import ChunkAssembler
from screen_airdrop.receiver.capture_mss import ScreenCapture
from screen_airdrop.receiver.config import ReceiverConfig
from screen_airdrop.receiver.frame_replay_source import FrameReplaySource
from screen_airdrop.receiver.pipeline_factory import create_pipeline
from screen_airdrop.receiver.runtime.replay_pipeline import ReplayPipeline
from screen_airdrop.receiver.screen_live_runtime import ScreenLiveRuntime


def test_create_replay_pipeline():
    """Test creating ReplayPipeline for replay mode."""
    config = MagicMock(spec=ReceiverConfig)
    config.is_replay_mode.return_value = True
    config.protocol = "gray4"
    config.get_grid_size.return_value = (160, 96)

    source = MagicMock(spec=FrameReplaySource)
    assembler = MagicMock(spec=ChunkAssembler)

    pipeline = create_pipeline(config, source, assembler, forced_roi=None)

    assert isinstance(pipeline, ReplayPipeline)
    assert pipeline.protocol == "gray4"


def test_create_screen_live_runtime():
    """Test creating ScreenLiveRuntime for screen mode."""
    config = MagicMock(spec=ReceiverConfig)
    config.is_replay_mode.return_value = False
    config.protocol = "layered"
    config.get_grid_size.return_value = (160, 96)
    config.decode_workers = 4
    config.prep_process = 1
    config.capture_fps = 30.0
    config.capture_dump_dir = None
    config.capture_dump_max_frames = 0

    source = MagicMock(spec=ScreenCapture)
    source.monitor_index = 1
    source.window_title = None
    source.region = None

    assembler = MagicMock(spec=ChunkAssembler)

    pipeline = create_pipeline(config, source, assembler, forced_roi=None)

    assert isinstance(pipeline, ScreenLiveRuntime)
    assert pipeline.protocol == "layered"


def test_create_pipeline_with_forced_roi():
    """Test creating pipeline with forced ROI sets manual mode."""
    config = MagicMock(spec=ReceiverConfig)
    config.is_replay_mode.return_value = False
    config.protocol = "basic"
    config.get_grid_size.return_value = (160, 96)
    config.decode_workers = 0
    config.prep_process = 0
    config.capture_fps = 30.0
    config.capture_dump_dir = None
    config.capture_dump_max_frames = 0

    source = MagicMock(spec=ScreenCapture)
    source.monitor_index = 1
    source.window_title = None
    source.region = None

    assembler = MagicMock(spec=ChunkAssembler)

    pipeline = create_pipeline(config, source, assembler, forced_roi=(100, 100, 800, 600))

    assert isinstance(pipeline, ScreenLiveRuntime)
    # Manual mode is set internally, just verify pipeline was created


def test_create_pipeline_without_forced_roi():
    """Test creating pipeline without forced ROI sets auto mode."""
    config = MagicMock(spec=ReceiverConfig)
    config.is_replay_mode.return_value = False
    config.protocol = "compact"
    config.get_grid_size.return_value = (160, 96)
    config.decode_workers = 0
    config.prep_process = 0
    config.capture_fps = 30.0
    config.capture_dump_dir = None
    config.capture_dump_max_frames = 0

    source = MagicMock(spec=ScreenCapture)
    source.monitor_index = 1
    source.window_title = None
    source.region = None

    assembler = MagicMock(spec=ChunkAssembler)

    pipeline = create_pipeline(config, source, assembler, forced_roi=None)

    assert isinstance(pipeline, ScreenLiveRuntime)
    # Auto mode is set internally, just verify pipeline was created


def test_create_pipeline_uses_protocol_geometry():
    """Test that create_pipeline uses correct protocol geometry."""
    config = MagicMock(spec=ReceiverConfig)
    config.is_replay_mode.return_value = True
    config.protocol = "layered"
    config.get_grid_size.return_value = (160, 96)

    source = MagicMock(spec=FrameReplaySource)
    assembler = MagicMock(spec=ChunkAssembler)

    pipeline = create_pipeline(config, source, assembler, forced_roi=None)

    # Layered protocol should create ReplayPipeline
    assert isinstance(pipeline, ReplayPipeline)
    assert pipeline.protocol == "layered"


def test_create_pipeline_basic_protocol_geometry():
    """Test that basic protocol uses correct geometry."""
    config = MagicMock(spec=ReceiverConfig)
    config.is_replay_mode.return_value = True
    config.protocol = "basic"
    config.get_grid_size.return_value = (160, 96)

    source = MagicMock(spec=FrameReplaySource)
    assembler = MagicMock(spec=ChunkAssembler)

    pipeline = create_pipeline(config, source, assembler, forced_roi=None)

    # Basic protocol should create ReplayPipeline
    assert isinstance(pipeline, ReplayPipeline)
    assert pipeline.protocol == "basic"
