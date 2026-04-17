"""Shared mapping from transport decode results to information-layer objects."""

from __future__ import annotations

from screen_airdrop.common.control_plane import control_kind_from_wire_chunk_id
from screen_airdrop.common.information import CodedUnit, SystematicUnit
from screen_airdrop.common.transport import CodedPayloadStatus, decode_coded_payload
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
            coded_payload = decode_coded_payload(payload)
            if coded_payload.status == CodedPayloadStatus.MALFORMED:
                return DecodedFrame(
                    frame_header=header,
                    payload=payload,
                    meta=meta,
                    control_kind=None,
                    transmission_unit=None,
                    invalid_data_payload=True,
                    invalid_data_reason=str(coded_payload.error),
                )
            if coded_payload.status == CodedPayloadStatus.VALID and coded_payload.decoded is not None:
                transmission_unit = CodedUnit(
                    session_id=int(getattr(header, "session_id", 0)),
                    generation_id=0,
                    generation_size=0,
                    equation_id=int(coded_payload.decoded.equation_id),
                    coding_seed=int(coded_payload.decoded.coding_seed),
                    degree=int(coded_payload.decoded.degree),
                    coding_scheme=coded_payload.decoded.coding_scheme,
                    payload_size=len(coded_payload.decoded.payload),
                    payload=coded_payload.decoded.payload,
                )
            else:
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
        invalid_data_payload=False,
        invalid_data_reason="",
    )
