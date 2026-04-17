"""Common transport-layer shared package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.common.transport.coded_payload import (
        CODED_PAYLOAD_ENVELOPE_VERSION,
        CodedPayloadParseResult,
        CodedPayloadStatus,
        DecodedCodedPayload,
        coded_payload_overhead_bytes,
        decode_coded_payload,
        encode_coded_payload,
    )
    from screen_airdrop.common.transport.protocol_interface import (
        DecodedFrame,
        LayoutInfo,
        ProtocolDecoder,
        ProtocolEncoder,
        TransportDecodeResult,
    )

__all__ = [
    "CodedPayloadParseResult",
    "CodedPayloadStatus",
    "CODED_PAYLOAD_ENVELOPE_VERSION",
    "DecodedFrame",
    "DecodedCodedPayload",
    "LayoutInfo",
    "ProtocolDecoder",
    "ProtocolEncoder",
    "TransportDecodeResult",
    "coded_payload_overhead_bytes",
    "decode_coded_payload",
    "encode_coded_payload",
]


def __getattr__(name):
    if name in {
        "CodedPayloadParseResult",
        "CodedPayloadStatus",
        "CODED_PAYLOAD_ENVELOPE_VERSION",
        "DecodedCodedPayload",
        "coded_payload_overhead_bytes",
        "decode_coded_payload",
        "encode_coded_payload",
    }:
        from screen_airdrop.common.transport import coded_payload as _coded_payload

        return getattr(_coded_payload, name)
    if name in __all__:
        from screen_airdrop.common.transport import protocol_interface as _protocol_interface

        return getattr(_protocol_interface, name)
    raise AttributeError(name)
