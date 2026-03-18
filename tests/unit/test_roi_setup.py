"""Tests for roi_setup module."""

from unittest.mock import MagicMock, patch

import pytest

from screen_airdrop.receiver.config import ReceiverConfig
from screen_airdrop.receiver.roi_policy import RoiPolicy
from screen_airdrop.receiver.roi_setup import _parse_region, setup_roi
from screen_airdrop.receiver.stats import TransferStats


def test_parse_region_valid():
    """Test parsing valid region string."""
    roi = _parse_region("100,200,300,400")
    assert roi == (100, 200, 300, 400)


def test_parse_region_with_spaces():
    """Test parsing region string with spaces."""
    roi = _parse_region("100, 200, 300, 400")
    assert roi == (100, 200, 300, 400)


def test_parse_region_none():
    """Test parsing None returns None."""
    roi = _parse_region(None)
    assert roi is None


def test_parse_region_empty_string():
    """Test parsing empty string returns None."""
    roi = _parse_region("")
    assert roi is None


def test_parse_region_invalid_format():
    """Test parsing invalid format raises ValueError."""
    with pytest.raises(ValueError, match="region/roi must be x,y,w,h"):
        _parse_region("100,200,300")


def test_setup_roi_from_cli():
    """Test setup_roi with CLI ROI argument."""
    config = MagicMock(spec=ReceiverConfig)
    config.roi = "100,200,300,400"
    config.region = None
    config.roi_profile = None
    config.source = "screen"

    roi_policy = MagicMock(spec=RoiPolicy)
    roi_policy.report_mode = "manual"
    roi_policy.mode = "manual"
    roi_policy.interactive = False
    roi_policy.requires_manual_roi.return_value = False

    stats = MagicMock(spec=TransferStats)

    roi = setup_roi(config, roi_policy, stats)
    assert roi == (100, 200, 300, 400)
    stats.set_roi_mode.assert_called_once_with("manual")


def test_setup_roi_from_region_fallback():
    """Test setup_roi falls back to --region if --roi not provided."""
    config = MagicMock(spec=ReceiverConfig)
    config.roi = None
    config.region = "50,60,700,800"
    config.roi_profile = None
    config.source = "screen"

    roi_policy = MagicMock(spec=RoiPolicy)
    roi_policy.report_mode = "manual"
    roi_policy.mode = "manual"
    roi_policy.interactive = False
    roi_policy.requires_manual_roi.return_value = False

    stats = MagicMock(spec=TransferStats)

    roi = setup_roi(config, roi_policy, stats)
    assert roi == (50, 60, 700, 800)


@patch("screen_airdrop.receiver.roi_setup.load_profile")
def test_setup_roi_from_profile(mock_load_profile):
    """Test setup_roi loads ROI from profile."""
    mock_load_profile.return_value = (10, 20, 300, 400)

    config = MagicMock(spec=ReceiverConfig)
    config.roi = None
    config.region = None
    config.roi_profile = "/path/to/profile.json"
    config.source = "screen"

    roi_policy = MagicMock(spec=RoiPolicy)
    roi_policy.report_mode = "manual"
    roi_policy.mode = "manual"
    roi_policy.interactive = False
    roi_policy.requires_manual_roi.return_value = False

    stats = MagicMock(spec=TransferStats)

    roi = setup_roi(config, roi_policy, stats)
    assert roi == (10, 20, 300, 400)
    mock_load_profile.assert_called_once_with("/path/to/profile.json")


def test_setup_roi_none_for_auto_mode():
    """Test setup_roi returns None for auto mode."""
    config = MagicMock(spec=ReceiverConfig)
    config.roi = None
    config.region = None
    config.roi_profile = None
    config.source = "screen"

    roi_policy = MagicMock(spec=RoiPolicy)
    roi_policy.report_mode = "auto"
    roi_policy.mode = "auto"
    roi_policy.interactive = False
    roi_policy.requires_manual_roi.return_value = False

    stats = MagicMock(spec=TransferStats)

    roi = setup_roi(config, roi_policy, stats)
    assert roi is None


def test_setup_roi_manual_mode_requires_roi():
    """Test setup_roi raises ValueError if manual mode requires ROI but none provided."""
    config = MagicMock(spec=ReceiverConfig)
    config.roi = None
    config.region = None
    config.roi_profile = None
    config.source = "screen"

    roi_policy = MagicMock(spec=RoiPolicy)
    roi_policy.report_mode = "manual"
    roi_policy.mode = "manual"
    roi_policy.interactive = False
    roi_policy.requires_manual_roi.return_value = True

    stats = MagicMock(spec=TransferStats)

    with pytest.raises(ValueError, match="manual roi-mode requires"):
        setup_roi(config, roi_policy, stats)


@patch("screen_airdrop.receiver.roi_setup.save_profile")
@patch("screen_airdrop.receiver.roi_setup.select_region")
@patch("screen_airdrop.receiver.roi_setup.get_monitor_region")
def test_setup_roi_interactive_selection(mock_get_monitor, mock_select, mock_save):
    """Test setup_roi with interactive selection."""
    mock_get_monitor.return_value = (0, 0, 1920, 1080)
    mock_select.return_value = (100, 100, 800, 600)

    config = MagicMock(spec=ReceiverConfig)
    config.roi = None
    config.region = None
    config.roi_profile = "/path/to/profile.json"
    config.source = "screen"
    config.monitor_index = 1

    roi_policy = MagicMock(spec=RoiPolicy)
    roi_policy.report_mode = "manual"
    roi_policy.mode = "manual"
    roi_policy.interactive = True
    roi_policy.requires_manual_roi.return_value = False

    stats = MagicMock(spec=TransferStats)

    roi = setup_roi(config, roi_policy, stats)
    assert roi == (100, 100, 800, 600)
    mock_select.assert_called_once_with((0, 0, 1920, 1080))
    mock_save.assert_called_once_with("/path/to/profile.json", (100, 100, 800, 600), 1)
    stats.mark_manual_select_attempt.assert_called_once()
    stats.mark_manual_roi.assert_called_once_with(switched=False)


@patch("screen_airdrop.receiver.roi_setup.select_region")
@patch("screen_airdrop.receiver.roi_setup.get_monitor_region")
def test_setup_roi_interactive_selection_canceled(mock_get_monitor, mock_select):
    """Test setup_roi raises RuntimeError if interactive selection is canceled."""
    mock_get_monitor.return_value = (0, 0, 1920, 1080)
    mock_select.return_value = None

    config = MagicMock(spec=ReceiverConfig)
    config.roi = None
    config.region = None
    config.roi_profile = None
    config.source = "screen"
    config.monitor_index = 1

    roi_policy = MagicMock(spec=RoiPolicy)
    roi_policy.report_mode = "manual"
    roi_policy.mode = "manual"
    roi_policy.interactive = True
    roi_policy.requires_manual_roi.return_value = False

    stats = MagicMock(spec=TransferStats)

    with pytest.raises(RuntimeError, match="manual roi selection canceled"):
        setup_roi(config, roi_policy, stats)
