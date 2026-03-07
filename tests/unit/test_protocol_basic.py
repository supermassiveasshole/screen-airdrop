from screen_airdrop.common.protocol_basic import (
    FRAME_DATA,
    FrameHeaderBasic,
    decode_header_and_payload_bits,
    encode_header_and_payload_bits,
)


def test_v3_header_payload_bits_roundtrip():
    payload = b"hello-v3-roundtrip"
    header = FrameHeaderBasic.make(
        frame_type=FRAME_DATA,
        session_id=42,
        epoch_id=3,
        frame_id=7,
        total_frames=9,
        chunk_id=5,
        payload=payload,
    )
    bits = encode_header_and_payload_bits(header, payload, ecc_level="Q")
    parsed, restored = decode_header_and_payload_bits(bits, ecc_level="Q")
    assert parsed.magic == header.magic
    assert parsed.frame_type == FRAME_DATA
    assert restored == payload
