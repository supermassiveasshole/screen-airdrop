from types import SimpleNamespace

import pytest

from screen_airdrop.common.information import CodedUnit, CodingScheme
from screen_airdrop.common.transport import (
    CODED_PAYLOAD_ENVELOPE_VERSION,
    CodedPayloadStatus,
    coded_payload_overhead_bytes,
    decode_coded_payload,
    encode_coded_payload,
)
from screen_airdrop.common.transport.protocol_basic import FRAME_DATA
from screen_airdrop.receiver.transport.result_mapping import build_transport_decode_result

pytestmark = pytest.mark.erasure_experiment


def test_coded_payload_roundtrip():
    payload = encode_coded_payload(
        equation_id=7,
        coding_seed=13,
        degree=3,
        payload=b"abc",
    )

    decoded = decode_coded_payload(payload)

    assert decoded.status == CodedPayloadStatus.VALID
    assert decoded.decoded is not None
    assert decoded.decoded.envelope_version == CODED_PAYLOAD_ENVELOPE_VERSION
    assert decoded.decoded.coding_scheme == CodingScheme.GF256_SEED_V2
    assert decoded.decoded.equation_id == 7
    assert decoded.decoded.coding_seed == 13
    assert decoded.decoded.degree == 3
    assert decoded.decoded.payload == b"abc"
    assert coded_payload_overhead_bytes() < len(payload)


def test_systematic_payload_is_not_detected_as_coded():
    assert decode_coded_payload(b"plain-systematic-payload").status == CodedPayloadStatus.NOT_CODED


def test_malformed_coded_payload_is_reported():
    malformed = b"SARCODE1" + (7).to_bytes(4, "big") + (9).to_bytes(4, "big") + (0).to_bytes(2, "big")

    decoded = decode_coded_payload(malformed)

    assert decoded.status == CodedPayloadStatus.MALFORMED
    assert decoded.error


def test_transport_result_mapping_builds_coded_unit_from_envelope():
    header = SimpleNamespace(
        frame_type=FRAME_DATA,
        session_id=42,
        chunk_id=5,
    )
    payload = encode_coded_payload(
        equation_id=9,
        coding_seed=21,
        degree=2,
        payload=b"\x01\x02",
    )

    decoded = build_transport_decode_result(header, payload, meta=SimpleNamespace())

    assert isinstance(decoded.transmission_unit, CodedUnit)
    assert decoded.transmission_unit.coding_scheme == CodingScheme.GF256_SEED_V2
    assert decoded.transmission_unit.equation_id == 9
    assert decoded.transmission_unit.coding_seed == 21
    assert decoded.transmission_unit.degree == 2
    assert decoded.transmission_unit.payload == b"\x01\x02"


def test_coded_payload_roundtrip_supports_legacy_v1_scheme():
    payload = encode_coded_payload(
        equation_id=2,
        coding_seed=8,
        degree=2,
        coding_scheme=CodingScheme.GF256_SEED_V1,
        payload=b"\x05\x06",
    )

    decoded = decode_coded_payload(payload)

    assert decoded.status == CodedPayloadStatus.VALID
    assert decoded.decoded is not None
    assert decoded.decoded.coding_scheme == CodingScheme.GF256_SEED_V1


def test_transport_result_mapping_marks_malformed_coded_payload_invalid():
    header = SimpleNamespace(
        frame_type=FRAME_DATA,
        session_id=42,
        chunk_id=5,
    )
    malformed = b"SARCODE1" + (1).to_bytes(4, "big") + (2).to_bytes(4, "big") + (0).to_bytes(2, "big")

    decoded = build_transport_decode_result(header, malformed, meta=SimpleNamespace())

    assert decoded.transmission_unit is None
    assert decoded.invalid_data_payload is True
    assert decoded.invalid_data_reason
