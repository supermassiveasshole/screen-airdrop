from screen_airdrop.common.protocol import FRAME_DATA, PROTOCOL_VERSION_V2, FrameHeader
from screen_airdrop.receiver.locator import detect_locator_bbox
from screen_airdrop.sender.encoder import build_v2_layout, encode_frame


def test_locator_bbox_on_v2_frame_is_stable():
    width, height, block_size = 1440, 900, 6
    payload = b"a" * 2000
    header = FrameHeader.make(
        frame_type=FRAME_DATA,
        session_id=1,
        epoch_id=1,
        frame_id=1,
        total_frames=1,
        chunk_id=1,
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
    expected = (
        layout.canvas_x - layout.border_px,
        layout.canvas_y - layout.border_px,
        layout.canvas_w + 2 * layout.border_px,
        layout.canvas_h + 2 * layout.border_px,
    )
    result = detect_locator_bbox(frame, threshold=127)
    assert result is not None
    x, y, w, h = result.bbox
    ex, ey, ew, eh = expected
    assert abs(x - ex) <= block_size
    assert abs(y - ey) <= block_size
    assert abs(w - ew) <= 2 * block_size
    assert abs(h - eh) <= 2 * block_size

