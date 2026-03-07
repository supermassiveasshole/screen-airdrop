from screen_airdrop.common.protocol import FRAME_DATA, FrameHeader


def test_header_roundtrip():
    payload = b"hello"
    header = FrameHeader.make(
        frame_type=FRAME_DATA,
        session_id=123,
        epoch_id=1,
        frame_id=2,
        total_frames=3,
        chunk_id=4,
        payload=payload,
    )
    raw = header.pack()
    parsed = FrameHeader.unpack(raw)
    assert parsed.session_id == 123
    assert parsed.chunk_id == 4
    assert parsed.payload_len == len(payload)
