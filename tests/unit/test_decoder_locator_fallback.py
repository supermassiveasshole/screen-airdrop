import numpy as np

from screen_airdrop.common.protocol import FRAME_DATA, PROTOCOL_VERSION_V2, FrameHeader
from screen_airdrop.receiver.decoder import decode_frame
from screen_airdrop.sender.encoder import encode_frame


def test_decode_v2_fallback_when_projection_is_misled():
    sender_w, sender_h, block_size = 1368, 738, 6
    payload = b"fallback-check-payload" * 20
    header = FrameHeader.make(
        frame_type=FRAME_DATA,
        session_id=123,
        epoch_id=1,
        frame_id=1,
        total_frames=1,
        chunk_id=0,
        payload=payload,
        version=PROTOCOL_VERSION_V2,
    )
    sender_frame = encode_frame(
        header=header,
        payload=payload,
        width=sender_w,
        height=sender_h,
        block_size=block_size,
        quiet_zone_px=48,
    )
    frame = sender_frame.copy()

    # Simulate desktop capture: sender window is below a bright menu/title bar.
    desktop_h, desktop_w = 900, 1440
    desktop = np.zeros((desktop_h, desktop_w, 3), dtype=frame.dtype)
    desktop[0:28, :, :] = 255
    desktop[60:90, :, :] = 220
    ox, oy = 36, 126
    desktop[oy : oy + sender_h, ox : ox + sender_w, :] = frame

    decoded_header, decoded_payload, _ = decode_frame(
        frame=desktop,
        block_size=block_size,
        threshold=127,
        protocol="v2",
        forced_roi=None,
    )
    assert decoded_header.version == PROTOCOL_VERSION_V2
    assert decoded_payload == payload
