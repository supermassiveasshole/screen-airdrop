"""Registry-backed locator assembly for live and replay decode paths."""

from __future__ import annotations

from typing import Callable, Optional, Tuple, cast

from screen_airdrop.receiver.locator.basic import LocateError, locate_frame, locate_frame_legacy
from screen_airdrop.receiver.locator.frame_locator import FrameLocator

FrameLocatorBuilder = Callable[..., FrameLocator]
GeometryLocatorBuilder = Callable[[object], object]


def auto_locator_with_fallback(frame, search_roi, config=None):
    """Precise locator with legacy fallback on failure or weak confidence."""
    result = locate_frame(frame, search_roi, config)
    if isinstance(result, LocateError) or result.quality.confidence < 0.55:
        result = locate_frame_legacy(frame, search_roi, config)
        if hasattr(result, "quad_src") and not hasattr(result, "locator_engine"):
            setattr(result, "locator_engine", "legacy")
        return result
    if hasattr(result, "quad_src") and not hasattr(result, "locator_engine"):
        setattr(result, "locator_engine", "auto")
    return result


def _build_auto_frame_locator(
    *,
    grid_w: int,
    grid_h: int,
    guard_band: int,
    corner_size: int,
    initial_roi: Optional[Tuple[int, int, int, int]] = None,
) -> FrameLocator:
    return FrameLocator(
        locator_func=auto_locator_with_fallback,
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=guard_band,
        corner_size=corner_size,
        initial_roi=initial_roi,
        fixed_roi=False,
    )


def _build_manual_frame_locator(
    *,
    grid_w: int,
    grid_h: int,
    guard_band: int,
    corner_size: int,
    initial_roi: Optional[Tuple[int, int, int, int]] = None,
) -> FrameLocator:
    return FrameLocator(
        locator_func=locate_frame_legacy,
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=guard_band,
        corner_size=corner_size,
        initial_roi=initial_roi,
        fixed_roi=True,
    )


class ProtocolGeometryLocator:
    """Protocol-aware locator wrapper used only for replay diagnostics/stateful replay."""

    def __init__(self, decoder):
        self._decoder = decoder

    def locate(self, frame):
        return self._decoder.locate_geometry(
            frame=frame,
            detect_mode="full",
            forced_roi=None,
        )

    def get_current_roi(self):
        return None

    def update_roi_from_bbox(self, bbox):
        del bbox

    def reset_roi(self):
        return None


def _build_protocol_geometry_locator(decoder) -> ProtocolGeometryLocator:
    return ProtocolGeometryLocator(decoder)


_FRAME_LOCATOR_BUILDERS: dict[str, FrameLocatorBuilder] = {
    "auto": _build_auto_frame_locator,
    "manual": _build_manual_frame_locator,
}

_GEOMETRY_LOCATOR_BUILDERS: dict[str, GeometryLocatorBuilder] = {
    "protocol": _build_protocol_geometry_locator,
}


def register_frame_locator_builder(name: str, builder: FrameLocatorBuilder) -> None:
    """Register or replace a named stateful frame locator builder."""
    _FRAME_LOCATOR_BUILDERS[str(name)] = builder


def get_frame_locator_builder(name: str) -> FrameLocatorBuilder:
    """Return the registered frame locator builder for a locator kind."""
    try:
        return _FRAME_LOCATOR_BUILDERS[str(name)]
    except KeyError as exc:
        raise ValueError(f"Unknown frame locator kind: {name}") from exc


def create_frame_locator(name: str, /, **kwargs) -> FrameLocator:
    """Instantiate a registered stateful frame locator."""
    builder = get_frame_locator_builder(name)
    return builder(**kwargs)


def registered_frame_locator_kinds():
    """Return registered frame locator kinds in deterministic order."""
    return tuple(sorted(_FRAME_LOCATOR_BUILDERS))


def register_geometry_locator_builder(name: str, builder: GeometryLocatorBuilder) -> None:
    """Register or replace a named geometry-locator builder."""
    _GEOMETRY_LOCATOR_BUILDERS[str(name)] = builder


def get_geometry_locator_builder(name: str) -> GeometryLocatorBuilder:
    """Return the registered geometry-locator builder for a locator kind."""
    try:
        return _GEOMETRY_LOCATOR_BUILDERS[str(name)]
    except KeyError as exc:
        raise ValueError(f"Unknown geometry locator kind: {name}") from exc


def create_geometry_locator(name: str, /, decoder):
    """Instantiate a registered geometry locator."""
    builder = get_geometry_locator_builder(name)
    return builder(decoder)


def registered_geometry_locator_kinds():
    """Return registered geometry locator kinds in deterministic order."""
    return tuple(sorted(_GEOMETRY_LOCATOR_BUILDERS))


def build_frame_locator(
    *,
    grid_w: int,
    grid_h: int,
    guard_band: int,
    corner_size: int,
    initial_roi: Optional[Tuple[int, int, int, int]] = None,
    manual_mode: bool = False,
) -> FrameLocator:
    """Create the repository-standard stateful frame locator."""
    kind = "manual" if manual_mode else "auto"
    return create_frame_locator(
        kind,
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=guard_band,
        corner_size=corner_size,
        initial_roi=initial_roi,
    )


def build_protocol_geometry_locator(decoder) -> ProtocolGeometryLocator:
    """Build a replay-only protocol-aware locator wrapper."""
    return cast(ProtocolGeometryLocator, create_geometry_locator("protocol", decoder=decoder))
