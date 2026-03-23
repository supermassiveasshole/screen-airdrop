"""Factory for creating protocol-specific decoders."""

from screen_airdrop.common.transport.protocol_interface import ProtocolDecoder
from screen_airdrop.receiver.transport.basic.adapter import BasicProtocolDecoder
from screen_airdrop.receiver.transport.compact.adapter import CompactProtocolDecoder
from screen_airdrop.receiver.transport.gray4.adapter import Gray4ProtocolDecoder
from screen_airdrop.receiver.transport.layered.adapter import LayeredProtocolDecoder


def create_protocol_decoder(
    protocol: str,
    grid_w: int,
    grid_h: int,
    guard_band: int,
    corner_size: int,
    locator_engine: str = "auto",
    locator_confidence_threshold: float = 0.55,
) -> ProtocolDecoder:
    if protocol == "basic":
        return BasicProtocolDecoder(
            grid_w=grid_w,
            grid_h=grid_h,
            guard_band=guard_band,
            corner_size=corner_size,
            locator_engine=locator_engine,
            locator_confidence_threshold=locator_confidence_threshold,
        )
    if protocol == "compact":
        return CompactProtocolDecoder(
            grid_w=grid_w,
            grid_h=grid_h,
            guard_band=guard_band,
            corner_size=corner_size,
            locator_engine=locator_engine,
            locator_confidence_threshold=locator_confidence_threshold,
        )
    if protocol == "gray4":
        return Gray4ProtocolDecoder(
            grid_w=grid_w,
            grid_h=grid_h,
            guard_band=guard_band,
            corner_size=corner_size,
            locator_engine=locator_engine,
            locator_confidence_threshold=locator_confidence_threshold,
        )
    if protocol == "layered":
        return LayeredProtocolDecoder(
            grid_w=grid_w,
            grid_h=grid_h,
            guard_band=guard_band,
            corner_size=corner_size,
            locator_engine=locator_engine,
            locator_confidence_threshold=locator_confidence_threshold,
        )
    raise ValueError(f"Unknown protocol: {protocol}")
