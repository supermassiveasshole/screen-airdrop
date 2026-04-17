"""Protocol-agnostic coded payload envelope helpers."""

from __future__ import annotations

import enum
import struct
from dataclasses import dataclass
from typing import Optional

from screen_airdrop.common.information import CodingScheme

CODED_PAYLOAD_MAGIC = b"SARCODE1"
CODED_PAYLOAD_ENVELOPE_VERSION = 2
_CODED_PAYLOAD_HEADER = struct.Struct(">8sBBIIH")
_SCHEME_TO_WIRE = {
    CodingScheme.GF256_SEED_V1: 1,
    CodingScheme.GF256_SEED_V2: 2,
}
_WIRE_TO_SCHEME = {
    wire_id: scheme for scheme, wire_id in _SCHEME_TO_WIRE.items()
}


@dataclass(frozen=True)
class DecodedCodedPayload:
    """Parsed coded payload envelope."""

    envelope_version: int
    coding_scheme: CodingScheme
    equation_id: int
    coding_seed: int
    degree: int
    payload: bytes


class CodedPayloadStatus(enum.Enum):
    NOT_CODED = "not_coded"
    MALFORMED = "malformed"
    VALID = "valid"


@dataclass(frozen=True)
class CodedPayloadParseResult:
    """Tri-state coded payload parse result."""

    status: CodedPayloadStatus
    decoded: Optional[DecodedCodedPayload] = None
    error: str = ""


def coded_payload_overhead_bytes() -> int:
    """Return the envelope overhead in bytes."""
    return _CODED_PAYLOAD_HEADER.size


def encode_coded_payload(
    *,
    equation_id: int,
    coding_seed: int,
    degree: int,
    coding_scheme: CodingScheme = CodingScheme.GF256_SEED_V2,
    payload: bytes,
) -> bytes:
    """Wrap coded payload metadata into the transport data payload."""
    scheme = coding_scheme if isinstance(coding_scheme, CodingScheme) else CodingScheme(str(coding_scheme))
    scheme_id = _SCHEME_TO_WIRE.get(scheme)
    if scheme_id is None:
        raise ValueError("unsupported coding_scheme")
    return _CODED_PAYLOAD_HEADER.pack(
        CODED_PAYLOAD_MAGIC,
        int(CODED_PAYLOAD_ENVELOPE_VERSION),
        int(scheme_id),
        int(equation_id),
        int(coding_seed),
        int(degree),
    ) + payload


def decode_coded_payload(payload: bytes) -> CodedPayloadParseResult:
    """Parse a coded payload envelope if present."""
    if len(payload) < _CODED_PAYLOAD_HEADER.size:
        if payload.startswith(CODED_PAYLOAD_MAGIC[: len(payload)]):
            return CodedPayloadParseResult(
                status=CodedPayloadStatus.MALFORMED,
                error="coded payload envelope too short",
            )
        return CodedPayloadParseResult(status=CodedPayloadStatus.NOT_CODED)
    magic, envelope_version, scheme_id, equation_id, coding_seed, degree = (
        _CODED_PAYLOAD_HEADER.unpack_from(payload)
    )
    if magic != CODED_PAYLOAD_MAGIC:
        return CodedPayloadParseResult(status=CodedPayloadStatus.NOT_CODED)
    if int(envelope_version) != int(CODED_PAYLOAD_ENVELOPE_VERSION):
        return CodedPayloadParseResult(
            status=CodedPayloadStatus.MALFORMED,
            error="unsupported coded payload envelope version",
        )
    coding_scheme = _WIRE_TO_SCHEME.get(int(scheme_id))
    if coding_scheme is None:
        return CodedPayloadParseResult(
            status=CodedPayloadStatus.MALFORMED,
            error="unsupported coding_scheme",
        )
    decoded_payload = payload[_CODED_PAYLOAD_HEADER.size :]
    if int(degree) <= 0:
        return CodedPayloadParseResult(
            status=CodedPayloadStatus.MALFORMED,
            error="degree must be positive",
        )
    if not decoded_payload:
        return CodedPayloadParseResult(
            status=CodedPayloadStatus.MALFORMED,
            error="coded payload must not be empty",
        )
    return CodedPayloadParseResult(
        status=CodedPayloadStatus.VALID,
        decoded=DecodedCodedPayload(
            envelope_version=int(envelope_version),
            coding_scheme=coding_scheme,
            equation_id=int(equation_id),
            coding_seed=int(coding_seed),
            degree=int(degree),
            payload=decoded_payload,
        ),
    )
