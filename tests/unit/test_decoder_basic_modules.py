from screen_airdrop.common.transport.protocol_basic import FRAME_DATA, FrameHeaderBasic
from screen_airdrop.receiver.transport.basic.decoder import decode_frame_basic
from screen_airdrop.sender.transport.basic.encoder import (
    build_symbol_modules_basic,
    encode_frame_basic,
)


def test_decode_v31_from_rendered_frame():
    payload = b"decoder-v31-frame-roundtrip"
    header = FrameHeaderBasic.make(
        frame_type=FRAME_DATA,
        session_id=123,
        epoch_id=1,
        frame_id=2,
        total_frames=5,
        chunk_id=2,
        payload=payload,
    )
    frame = encode_frame_basic(
        header=header,
        payload=payload,
        width=1920,
        height=1080,
        grid_w=160,
        grid_h=96,
        ecc_level="Q",
        guard_band=2,
        corner_size=9,
    )
    parsed, restored, meta = decode_frame_basic(
        frame=frame,
        detect_mode="full",
        grid_w=160,
        grid_h=96,
        guard_band=2,
        corner_size=9,
    )
    assert parsed.chunk_id == header.chunk_id
    assert restored == payload
    assert meta.protocol_version_used == 31


def test_build_v31_modules_size():
    payload = b"abc"
    header = FrameHeaderBasic.make(
        frame_type=FRAME_DATA,
        session_id=1,
        epoch_id=0,
        frame_id=0,
        total_frames=1,
        chunk_id=0,
        payload=payload,
    )
    modules = build_symbol_modules_basic(
        header=header,
        payload=payload,
        grid_w=160,
        grid_h=96,
        guard_band=2,
        corner_size=9,
    )
    # frame_h = 2*q + 2*F + 2*guard + Gy = 126
    # frame_w = 2*q + 2*F + 2*guard + Gx = 190
    assert modules.shape == (126, 190)
