from screen_airdrop.common.transport.protocol_basic import FRAME_DATA, FrameHeaderBasic
from screen_airdrop.receiver.transport.basic.detector import detect_symbol_bbox
from screen_airdrop.sender.transport.basic.encoder import encode_frame_basic


def test_detect_bbox_from_full_frame():
    payload = b"detector-basic"
    header = FrameHeaderBasic.make(
        frame_type=FRAME_DATA,
        session_id=11,
        epoch_id=0,
        frame_id=0,
        total_frames=1,
        chunk_id=0,
        payload=payload,
    )
    frame = encode_frame_basic(
        header=header,
        payload=payload,
        width=1280,
        height=720,
        guard_band=2,
        corner_size=9,
    )
    det = detect_symbol_bbox(frame)
    assert det is not None
    assert det.bbox[2] > 200
    assert det.bbox[3] > 100
