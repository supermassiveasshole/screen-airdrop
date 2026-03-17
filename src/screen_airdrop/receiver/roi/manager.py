"""ROI management for screen-airdrop receiver."""

from typing import Optional, Tuple

from screen_airdrop.receiver.roi.transforms import (
    build_track_roi_from_bbox,
    ensure_roi_valid,
    expand_roi_local,
    roi_abs_to_local,
    roi_local_to_abs,
)


class RoiManager:
    """Manages ROI coordinate transformations and tracking."""

    def __init__(self, capture_region: Optional[Tuple[int, int, int, int]] = None):
        """Initialize ROI manager.

        Args:
            capture_region: Capture region in absolute coordinates (x, y, w, h)
        """
        self.capture_region = capture_region

    def abs_to_local(
        self,
        roi_abs: Optional[Tuple[int, int, int, int]],
        frame_shape: Tuple[int, int, int],
    ) -> Optional[Tuple[int, int, int, int]]:
        """Convert absolute ROI to local frame coordinates.

        Args:
            roi_abs: ROI in absolute screen coordinates
            frame_shape: Frame shape (h, w, c)

        Returns:
            ROI in local frame coordinates
        """
        return roi_abs_to_local(roi_abs, self.capture_region, frame_shape)

    def local_to_abs(
        self,
        roi_local: Optional[Tuple[int, int, int, int]],
    ) -> Optional[Tuple[int, int, int, int]]:
        """Convert local frame ROI to absolute screen coordinates.

        Args:
            roi_local: ROI in local frame coordinates

        Returns:
            ROI in absolute screen coordinates
        """
        return roi_local_to_abs(roi_local, self.capture_region)

    def expand(
        self,
        roi_local: Optional[Tuple[int, int, int, int]],
        frame_shape: Tuple[int, int, int],
        pad_px: int,
    ) -> Optional[Tuple[int, int, int, int]]:
        """Expand ROI by padding.

        Args:
            roi_local: ROI in local frame coordinates
            frame_shape: Frame shape (h, w, c)
            pad_px: Padding in pixels

        Returns:
            Expanded ROI
        """
        return expand_roi_local(roi_local, frame_shape, pad_px)

    def build_track_roi(
        self,
        det_bbox: Tuple[int, int, int, int],
        frame_shape: Tuple[int, int, int],
        margin_px: int = 32,
    ) -> Tuple[int, int, int, int]:
        """Build tracking ROI from detected bbox.

        Args:
            det_bbox: Detected bounding box
            frame_shape: Frame shape (h, w, c)
            margin_px: Margin in pixels

        Returns:
            Tracking ROI
        """
        return build_track_roi_from_bbox(det_bbox, frame_shape, margin_px)

    @staticmethod
    def validate(roi: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        """Validate ROI dimensions.

        Args:
            roi: ROI to validate

        Returns:
            Validated ROI

        Raises:
            ValueError: If ROI is invalid
        """
        return ensure_roi_valid(roi)
