"""Shared mapping from transport decode results to information-layer objects."""

from __future__ import annotations

from screen_airdrop.common.control_plane import control_kind_from_wire_chunk_id
from screen_airdrop.common.information import SystematicUnit
from screen_airdrop.common.transport.protocol_basic import FRAME_DATA
from screen_airdrop.common.transport.protocol_interface import DecodedFrame


def build_transport_decode_result(header, payload: bytes, meta) -> DecodedFrame:
    """Build normalized transport decode result for current systematic-only phase.

    Generation identity is resolved later from generation control metadata.
    The transport layer only exposes local source_index from the current data frame.
    """
    control_kind = None
    transmission_unit = None

    if int(getattr(header, "frame_type", -1)) == int(FRAME_DATA):
        control_kind = control_kind_from_wire_chunk_id(int(getattr(header, "chunk_id", 0)))
        if control_kind is None and int(getattr(header, "chunk_id", 0)) > 0:
            transmission_unit = SystematicUnit(
                session_id=int(getattr(header, "session_id", 0)),
                generation_id=0,
                generation_size=0,
                source_index=int(getattr(header, "chunk_id", 0)),
                payload_size=len(payload),
                payload=payload,
            )

    return DecodedFrame(
        frame_header=header,
        payload=payload,
        meta=meta,
        control_kind=control_kind,
        transmission_unit=transmission_unit,
    )
