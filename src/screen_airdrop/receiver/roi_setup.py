"""ROI setup utilities for CLI."""

from typing import Optional, Tuple

from screen_airdrop.receiver.capture_mss import get_monitor_region
from screen_airdrop.receiver.config import ReceiverConfig
from screen_airdrop.receiver.roi import ensure_roi_valid
from screen_airdrop.receiver.roi_policy import RoiPolicy
from screen_airdrop.receiver.roi_profile import load_profile, save_profile
from screen_airdrop.receiver.roi_selector import select_region
from screen_airdrop.receiver.stats import TransferStats


def _parse_region(raw: Optional[str]) -> Optional[Tuple[int, int, int, int]]:
    """Parse region string to tuple.

    Args:
        raw: Region string in format "x,y,w,h"

    Returns:
        Tuple of (x, y, w, h) or None if raw is None

    Raises:
        ValueError: If format is invalid
    """
    if not raw:
        return None
    parts = [int(p.strip()) for p in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("region/roi must be x,y,w,h")
    return parts[0], parts[1], parts[2], parts[3]


def setup_roi(
    config: ReceiverConfig,
    roi_policy: RoiPolicy,
    stats: TransferStats,
) -> Optional[Tuple[int, int, int, int]]:
    """Setup ROI from config, profile, or interactive selection.

    This function handles:
    1. Parse CLI ROI or load from profile
    2. Validate ROI
    3. Check if manual ROI is required
    4. Interactive selection if needed
    5. Save profile if configured

    Args:
        config: Receiver configuration
        roi_policy: ROI policy
        stats: Transfer stats (for tracking manual selection)

    Returns:
        ROI as (x, y, w, h) or None for auto mode

    Raises:
        ValueError: If manual mode requires ROI but none provided
        RuntimeError: If interactive selection is canceled
    """
    # Set ROI mode on stats
    stats.set_roi_mode(roi_policy.report_mode)

    # Parse CLI ROI or load from profile
    cli_roi = _parse_region(config.roi) or _parse_region(config.region)
    profile_roi = load_profile(config.roi_profile) if config.roi_profile else None
    forced_roi = cli_roi or profile_roi

    # Validate ROI if present
    if forced_roi is not None:
        forced_roi = ensure_roi_valid(forced_roi)

    # Check if manual ROI is required but not provided
    if roi_policy.requires_manual_roi(forced_roi=forced_roi):
        raise ValueError("manual roi-mode requires --roi/--roi-profile or --roi-interactive")

    # Interactive ROI selection if needed
    if (
        config.source == "screen"
        and roi_policy.mode == "manual"
        and forced_roi is None
        and roi_policy.interactive
    ):
        stats.mark_manual_select_attempt()
        selected = select_region(get_monitor_region(config.monitor_index))
        if selected is None:
            import sys
            print("\nROI selection canceled. Exiting.", file=sys.stderr)
            sys.exit(0)
        forced_roi = ensure_roi_valid(selected)
        stats.mark_manual_roi(switched=False)

        # Save profile if configured
        if config.roi_profile:
            save_profile(config.roi_profile, forced_roi, config.monitor_index)

    return forced_roi
