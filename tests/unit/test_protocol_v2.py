from screen_airdrop.common.protocol import FRAME_DATA, PROTOCOL_VERSION_V2, FrameHeader


def test_v2_header_roundtrip():
    payload = b"hello-v2"
    header = FrameHeader.make(
        frame_type=FRAME_DATA,
        session_id=987,
        epoch_id=2,
        frame_id=3,
        total_frames=7,
        chunk_id=4,
        payload=payload,
        version=PROTOCOL_VERSION_V2,
        layout_id=1,
        canvas_w=1200,
        canvas_h=800,
        locator_crc=1234,
    )
    parsed = FrameHeader.unpack(header.pack())
    assert parsed.version == PROTOCOL_VERSION_V2
    assert parsed.layout_id == 1
    assert parsed.canvas_w == 1200
    assert parsed.canvas_h == 800
    assert parsed.chunk_id == 4
    assert parsed.payload_len == len(payload)
