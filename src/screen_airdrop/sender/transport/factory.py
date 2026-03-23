"""Factory for sender transport encoders."""

from screen_airdrop.common.transport.protocol_basic import ECC_LEVELS
from screen_airdrop.common.transport.protocol_interface import ProtocolEncoder
from screen_airdrop.sender.transport.basic.adapter import BasicProtocolEncoder
from screen_airdrop.sender.transport.compact.adapter import CompactProtocolEncoder
from screen_airdrop.sender.transport.gray4.adapter import Gray4ProtocolEncoder
from screen_airdrop.sender.transport.layered.adapter import LayeredProtocolEncoder


def create_transport_encoder(
    *,
    protocol: str,
    grid_w: int,
    grid_h: int,
    ecc_level: str,
    guard_band: int,
    corner_size: int,
    outer_padding_px: int,
    outer_padding_white: bool,
) -> ProtocolEncoder:
    if protocol in {"basic", "compact", "gray4"} and ecc_level not in ECC_LEVELS:
        raise RuntimeError(f"invalid ecc-level: {ecc_level}")
    if protocol == "basic":
        return BasicProtocolEncoder(
            grid_w=grid_w,
            grid_h=grid_h,
            ecc_level=ecc_level,
            guard_band=guard_band,
            corner_size=corner_size,
            outer_padding_px=outer_padding_px,
            outer_padding_white=outer_padding_white,
        )
    if protocol == "compact":
        return CompactProtocolEncoder(
            grid_w=grid_w,
            grid_h=grid_h,
            ecc_level=ecc_level,
            guard_band=guard_band,
            corner_size=corner_size,
            outer_padding_px=outer_padding_px,
            outer_padding_white=outer_padding_white,
        )
    if protocol == "gray4":
        return Gray4ProtocolEncoder(
            grid_w=grid_w,
            grid_h=grid_h,
            ecc_level=ecc_level,
            guard_band=guard_band,
            corner_size=corner_size,
            outer_padding_px=outer_padding_px,
            outer_padding_white=outer_padding_white,
        )
    if protocol == "layered":
        return LayeredProtocolEncoder(
            grid_w=grid_w,
            grid_h=grid_h,
            ecc_level=ecc_level,
            guard_band=guard_band,
            corner_size=corner_size,
            outer_padding_px=outer_padding_px,
            outer_padding_white=outer_padding_white,
        )
    raise ValueError(
        f"Protocol '{protocol}' not supported, use 'basic', 'compact', 'gray4', or 'layered'"
    )
