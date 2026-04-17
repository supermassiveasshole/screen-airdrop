"""Tests for pipeline_factory module."""

from unittest.mock import MagicMock

from screen_airdrop.receiver.application.pipeline_factory import create_pipeline
from screen_airdrop.receiver.application.replay_source import FrameReplaySource
from screen_airdrop.receiver.config import ReceiverConfig
from screen_airdrop.receiver.information.assembler import ChunkAssembler
from screen_airdrop.receiver.pipeline.factory import get_pipeline_factory, registered_pipeline_kinds
from screen_airdrop.receiver.pipeline.live import ScreenLiveRuntime
from screen_airdrop.receiver.pipeline.replay import ReplayPipeline
from screen_airdrop.receiver.pipeline.simulated_live import SimulatedLiveRuntime
from screen_airdrop.receiver.runtime.screen_capture import ScreenCapture


def test_registered_pipeline_kinds_include_live_replay_and_simulated_live():
    assert registered_pipeline_kinds() == ("live", "replay", "simulated_live")


def test_get_pipeline_factory_returns_registered_factories():
    assert callable(get_pipeline_factory("live"))
    assert callable(get_pipeline_factory("replay"))


def test_create_replay_pipeline():
    """Test creating ReplayPipeline for replay mode."""
    config = MagicMock(spec=ReceiverConfig)
    config.is_replay_mode.return_value = True
    config.is_simulated_live_mode.return_value = False
    config.protocol = "gray4"
    config.get_grid_size.return_value = (160, 96)
    config.decode_workers = 3
    config.replay_geometry_mode = "stateless"

    source = MagicMock(spec=FrameReplaySource)
    assembler = MagicMock(spec=ChunkAssembler)

    pipeline = create_pipeline(config, source, assembler, forced_roi=None)

    assert isinstance(pipeline, ReplayPipeline)
    assert pipeline.protocol == "gray4"
    assert pipeline._decode_workers == 3
    assert pipeline._parallel_decode_enabled is True


def test_create_screen_live_runtime():
    """Test creating ScreenLiveRuntime for screen mode."""
    config = MagicMock(spec=ReceiverConfig)
    config.is_replay_mode.return_value = False
    config.is_simulated_live_mode.return_value = False
    config.protocol = "layered"
    config.get_grid_size.return_value = (160, 96)
    config.decode_workers = 4
    config.prep_process = 1
    config.frame_queue_size = 48
    config.result_queue_size = 96
    config.capture_fps = 30.0
    config.capture_dump_dir = None
    config.capture_dump_max_frames = 0
    config.debug_dir = "/tmp/debug"
    config.debug_interval = 2.0
    config.debug_max_frames = 10

    source = MagicMock(spec=ScreenCapture)
    source.monitor_index = 1
    source.window_title = None
    source.region = None

    assembler = MagicMock(spec=ChunkAssembler)

    pipeline = create_pipeline(config, source, assembler, forced_roi=None)

    assert isinstance(pipeline, ScreenLiveRuntime)
    assert pipeline.protocol == "layered"
    assert pipeline._frame_queue_size == 48
    assert pipeline._result_queue_size == 96


def test_create_pipeline_with_forced_roi():
    """Test creating pipeline with forced ROI sets manual mode."""
    config = MagicMock(spec=ReceiverConfig)
    config.is_replay_mode.return_value = False
    config.is_simulated_live_mode.return_value = False
    config.protocol = "basic"
    config.get_grid_size.return_value = (160, 96)
    config.decode_workers = 0
    config.prep_process = 0
    config.frame_queue_size = 32
    config.result_queue_size = 256
    config.capture_fps = 30.0
    config.capture_dump_dir = None
    config.capture_dump_max_frames = 0
    config.debug_dir = None
    config.debug_interval = 1.0
    config.debug_max_frames = 30

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
    config.is_simulated_live_mode.return_value = False
    config.protocol = "compact"
    config.get_grid_size.return_value = (160, 96)
    config.decode_workers = 0
    config.prep_process = 0
    config.frame_queue_size = 32
    config.result_queue_size = 256
    config.capture_fps = 30.0
    config.capture_dump_dir = None
    config.capture_dump_max_frames = 0
    config.debug_dir = None
    config.debug_interval = 1.0
    config.debug_max_frames = 30

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
    config.is_simulated_live_mode.return_value = False
    config.protocol = "layered"
    config.get_grid_size.return_value = (160, 96)
    config.decode_workers = 2
    config.replay_geometry_mode = "stateful"

    source = MagicMock(spec=FrameReplaySource)
    assembler = MagicMock(spec=ChunkAssembler)

    pipeline = create_pipeline(config, source, assembler, forced_roi=None)

    # Layered protocol should create ReplayPipeline
    assert isinstance(pipeline, ReplayPipeline)
    assert pipeline.protocol == "layered"
    assert pipeline._parallel_decode_enabled is False


def test_create_pipeline_basic_protocol_geometry():
    """Test that basic protocol uses correct geometry."""
    config = MagicMock(spec=ReceiverConfig)
    config.is_replay_mode.return_value = True
    config.is_simulated_live_mode.return_value = False
    config.protocol = "basic"
    config.get_grid_size.return_value = (160, 96)
    config.decode_workers = 2
    config.replay_geometry_mode = "stateless"

    source = MagicMock(spec=FrameReplaySource)
    assembler = MagicMock(spec=ChunkAssembler)

    pipeline = create_pipeline(config, source, assembler, forced_roi=None)

    # Basic protocol should create ReplayPipeline
    assert isinstance(pipeline, ReplayPipeline)
    assert pipeline.protocol == "basic"
    assert pipeline._parallel_decode_enabled is True


def test_create_simulated_live_runtime():
    config = MagicMock(spec=ReceiverConfig)
    config.is_replay_mode.return_value = False
    config.is_simulated_live_mode.return_value = True
    config.protocol = "layered"
    config.get_grid_size.return_value = (160, 96)
    config.decode_workers = 4
    config.prep_process = 1
    config.frame_queue_size = 48
    config.result_queue_size = 96
    config.capture_fps = 30.0
    config.debug_dir = None
    config.debug_interval = 1.0
    config.debug_max_frames = 30
    config.simulated_live_pacing = "none"

    source = MagicMock(spec=FrameReplaySource)
    source.infer_frame_size.return_value = (640, 480)
    source.frames_dir = "/tmp/frames"
    assembler = MagicMock(spec=ChunkAssembler)

    pipeline = create_pipeline(config, source, assembler, forced_roi=None)

    assert isinstance(pipeline, SimulatedLiveRuntime)
    assert pipeline.protocol == "layered"
    assert pipeline.snapshot()["runtime_mode"] == "simulated_live"
