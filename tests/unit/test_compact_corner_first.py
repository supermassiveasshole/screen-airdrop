"""Test compact protocol corner-first detection with cropped frames."""

import numpy as np

from screen_airdrop.common.protocol_basic import FRAME_DATA, FrameHeaderBasic
from screen_airdrop.receiver.protocol_adapter_compact import CompactProtocolDecoder
from screen_airdrop.sender.protocol_adapter_compact import CompactProtocolEncoder


def test_compact_corner_first_full_frame():
    """Test corner-first detection with full uncropped frame."""
    encoder = CompactProtocolEncoder(grid_w=160, grid_h=96, ecc_level="L")
    decoder = CompactProtocolDecoder(grid_w=160, grid_h=96)

    payload = b"full-frame-test"
    header = FrameHeaderBasic.make(
        frame_type=FRAME_DATA,
        session_id=1,
        epoch_id=0,
        frame_id=0,
        total_frames=1,
        chunk_id=0,
        payload=payload,
    )

    frame = encoder.encode_frame(header, payload, 1920, 1080)
    decoded = decoder.decode_frame(frame)

    assert decoded.frame_header.session_id == 1
    assert decoded.payload == payload
    # Should use corner-first path
    assert decoded.meta.locator_engine in ("corner", "legacy")


def test_compact_corner_first_crop_top_bottom_white():
    """Test corner-first with top/bottom white borders cropped."""
    encoder = CompactProtocolEncoder(grid_w=160, grid_h=96, ecc_level="L")
    decoder = CompactProtocolDecoder(grid_w=160, grid_h=96)

    payload = b"crop-white-test"
    header = FrameHeaderBasic.make(
        frame_type=FRAME_DATA,
        session_id=2,
        epoch_id=0,
        frame_id=0,
        total_frames=1,
        chunk_id=0,
        payload=payload,
    )

    frame = encoder.encode_frame(header, payload, 1920, 1080)

    # Crop top and bottom white borders (keep 4 corners)
    # Find non-white region
    gray = frame.mean(axis=2).astype(np.uint8)
    rows_with_content = np.where(gray < 250)[0]

    if len(rows_with_content) > 0:
        y1 = max(0, rows_with_content[0] - 5)  # Keep some margin
        y2 = min(frame.shape[0], rows_with_content[-1] + 5)
        cropped = frame[y1:y2, :, :]

        decoded = decoder.decode_frame(cropped)

        assert decoded.frame_header.session_id == 2
        assert decoded.payload == payload


def test_compact_corner_first_crop_left_right_white():
    """Test corner-first with left/right white borders cropped."""
    encoder = CompactProtocolEncoder(grid_w=160, grid_h=96, ecc_level="L")
    decoder = CompactProtocolDecoder(grid_w=160, grid_h=96)

    payload = b"crop-sides-test"
    header = FrameHeaderBasic.make(
        frame_type=FRAME_DATA,
        session_id=3,
        epoch_id=0,
        frame_id=0,
        total_frames=1,
        chunk_id=0,
        payload=payload,
    )

    frame = encoder.encode_frame(header, payload, 1920, 1080)

    # Crop left and right white borders
    gray = frame.mean(axis=2).astype(np.uint8)
    cols_with_content = np.where(gray < 250)[1]

    if len(cols_with_content) > 0:
        x1 = max(0, cols_with_content[0] - 5)
        x2 = min(frame.shape[1], cols_with_content[-1] + 5)
        cropped = frame[:, x1:x2, :]

        decoded = decoder.decode_frame(cropped)

        assert decoded.frame_header.session_id == 3
        assert decoded.payload == payload


def test_compact_corner_first_crop_all_white():
    """Test corner-first with all white borders cropped (tight crop)."""
    encoder = CompactProtocolEncoder(grid_w=160, grid_h=96, ecc_level="L")
    decoder = CompactProtocolDecoder(grid_w=160, grid_h=96)

    payload = b"tight-crop-test"
    header = FrameHeaderBasic.make(
        frame_type=FRAME_DATA,
        session_id=4,
        epoch_id=0,
        frame_id=0,
        total_frames=1,
        chunk_id=0,
        payload=payload,
    )

    frame = encoder.encode_frame(header, payload, 1920, 1080)

    # Tight crop: remove all white borders
    gray = frame.mean(axis=2).astype(np.uint8)
    rows_with_content = np.where(gray < 250)[0]
    cols_with_content = np.where(gray < 250)[1]

    if len(rows_with_content) > 0 and len(cols_with_content) > 0:
        y1 = rows_with_content[0]
        y2 = rows_with_content[-1] + 1
        x1 = cols_with_content[0]
        x2 = cols_with_content[-1] + 1
        cropped = frame[y1:y2, x1:x2, :]

        decoded = decoder.decode_frame(cropped)

        assert decoded.frame_header.session_id == 4
        assert decoded.payload == payload


def test_compact_corner_first_asymmetric_crop():
    """Test corner-first with asymmetric cropping (mixed white/black borders)."""
    encoder = CompactProtocolEncoder(grid_w=160, grid_h=96, ecc_level="L")
    decoder = CompactProtocolDecoder(grid_w=160, grid_h=96)

    payload = b"asymmetric-crop"
    header = FrameHeaderBasic.make(
        frame_type=FRAME_DATA,
        session_id=5,
        epoch_id=0,
        frame_id=0,
        total_frames=1,
        chunk_id=0,
        payload=payload,
    )

    frame = encoder.encode_frame(header, payload, 1920, 1080)

    # Asymmetric crop: remove more from top/left than bottom/right
    gray = frame.mean(axis=2).astype(np.uint8)
    rows_with_content = np.where(gray < 250)[0]
    cols_with_content = np.where(gray < 250)[1]

    if len(rows_with_content) > 0 and len(cols_with_content) > 0:
        y1 = rows_with_content[0]  # Tight on top
        y2 = min(frame.shape[0], rows_with_content[-1] + 20)  # Loose on bottom
        x1 = cols_with_content[0]  # Tight on left
        x2 = min(frame.shape[1], cols_with_content[-1] + 20)  # Loose on right
        cropped = frame[y1:y2, x1:x2, :]

        decoded = decoder.decode_frame(cropped)

        assert decoded.frame_header.session_id == 5
        assert decoded.payload == payload
