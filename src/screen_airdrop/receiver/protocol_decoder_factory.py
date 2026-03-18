"""Factory for creating protocol-specific decoders."""

from typing import Union

from screen_airdrop.receiver.protocol_adapter_basic import BasicProtocolDecoder
from screen_airdrop.receiver.protocol_adapter_compact import CompactProtocolDecoder
from screen_airdrop.receiver.protocol_adapter_gray4 import Gray4ProtocolDecoder
from screen_airdrop.receiver.protocol_adapter_layered import LayeredProtocolDecoder


def create_protocol_decoder(
    protocol: str,
    grid_w: int,
    grid_h: int,
    guard_band: int,
    corner_size: int,
    locator_engine: str = "auto",
    locator_confidence_threshold: float = 0.55,
) -> Union[BasicProtocolDecoder, CompactProtocolDecoder, Gray4ProtocolDecoder, LayeredProtocolDecoder]:
    """Create protocol-specific decoder.

    Args:
        protocol: Protocol name (basic, compact, gray4, layered)
        grid_w: Grid width
        grid_h: Grid height
        guard_band: Guard band size
        corner_size: Corner finder size
        locator_engine: Locator engine type ("new", "legacy", "auto")
        locator_confidence_threshold: Locator confidence threshold

    Returns:
        Protocol decoder instance

    Raises:
        ValueError: If protocol is unknown
    """
    if protocol == "basic":
        return BasicProtocolDecoder(
            grid_w=grid_w,
            grid_h=grid_h,
            guard_band=guard_band,
            corner_size=corner_size,
            locator_engine=locator_engine,
            locator_confidence_threshold=locator_confidence_threshold,
        )
    elif protocol == "compact":
        return CompactProtocolDecoder(
            grid_w=grid_w,
            grid_h=grid_h,
            guard_band=guard_band,
            corner_size=corner_size,
            locator_engine=locator_engine,
            locator_confidence_threshold=locator_confidence_threshold,
        )
    elif protocol == "gray4":
        return Gray4ProtocolDecoder(
            grid_w=grid_w,
            grid_h=grid_h,
            guard_band=guard_band,
            corner_size=corner_size,
            locator_engine=locator_engine,
            locator_confidence_threshold=locator_confidence_threshold,
        )
    elif protocol == "layered":
        return LayeredProtocolDecoder(
            grid_w=grid_w,
            grid_h=grid_h,
            guard_band=guard_band,
            corner_size=corner_size,
            locator_engine=locator_engine,
            locator_confidence_threshold=locator_confidence_threshold,
        )
    else:
        raise ValueError(f"Unknown protocol: {protocol}")
