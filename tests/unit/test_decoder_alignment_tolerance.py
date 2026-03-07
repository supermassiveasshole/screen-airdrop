from screen_airdrop.common.protocol import FRAME_DATA, PROTOCOL_VERSION_V2, FrameHeader
from screen_airdrop.receiver.decoder import decode_frame
from screen_airdrop.sender.encoder import build_v2_layout, encode_frame


def test_decode_v2_with_full_locator_roi():
    width, height, block_size = 1440, 900, 6
    payload = b"alignment-tolerance" * 30
    header = FrameHeader.make(
        frame_type=FRAME_DATA,
        session_id=2,
        epoch_id=1,
        frame_id=1,
        total_frames=1,
        chunk_id=0,
        payload=payload,
        version=PROTOCOL_VERSION_V2,
    )
    frame = encode_frame(
        header=header,
        payload=payload,
        width=width,
        height=height,
        block_size=block_size,
        quiet_zone_px=48,
    )
    layout = build_v2_layout(width, height, block_size, quiet_zone_px=48)
    border = layout.border_px
    roi = (
        layout.canvas_x - border,
        layout.canvas_y - border,
        layout.canvas_w + 2 * border,
        layout.canvas_h + 2 * border,
    )

    decoded_header, decoded_payload, _ = decode_frame(
        frame=frame,
        block_size=block_size,
        threshold=127,
        protocol="v2",
        forced_roi=roi,
    )
    assert decoded_header.version == PROTOCOL_VERSION_V2
    assert decoded_payload == payload
