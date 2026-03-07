from screen_airdrop.common.protocol_v3 import V3_FRAME_DATA, FrameHeaderV3
from screen_airdrop.receiver.detector_v31 import detect_symbol_bbox_v31
from screen_airdrop.sender.encoder_v31 import encode_frame_v31


def test_detect_v31_bbox_from_full_frame():
    payload = b"detector-v31"
    header = FrameHeaderV3.make(
        frame_type=V3_FRAME_DATA,
        session_id=11,
        epoch_id=0,
        frame_id=0,
        total_frames=1,
        chunk_id=0,
        payload=payload,
    )
    frame = encode_frame_v31(
        header=header,
        payload=payload,
        width=1280,
        height=720,
        guard_band=2,
        corner_size=9,
    )
    det = detect_symbol_bbox_v31(frame)
    assert det is not None
    assert det.bbox[2] > 200
    assert det.bbox[3] > 100
