import numpy as np

from screen_airdrop.common.protocol_basic import FRAME_DATA, FrameHeaderBasic
from screen_airdrop.receiver.locator.basic import LocateError, LocatorConfig, locate_frame
from screen_airdrop.sender.encoder_basic import encode_frame_basic


def test_locator_v31_returns_modules_and_quad_contract():
    payload = b"locator-v31-roundtrip"
    header = FrameHeaderBasic.make(
        frame_type=FRAME_DATA,
        session_id=1,
        epoch_id=0,
        frame_id=1,
        total_frames=1,
        chunk_id=0,
        payload=payload,
    )
    frame = encode_frame_basic(
        header=header,
        payload=payload,
        width=1920,
        height=1080,
        grid_w=160,
        grid_h=96,
        guard_band=2,
        corner_size=9,
    )

    loc = locate_frame(frame, config=LocatorConfig(grid_w=160, grid_h=96))
    assert not isinstance(loc, LocateError)
    assert loc.modules.shape == (126, 190)
    assert loc.quad_src.shape == (4, 2)
    assert np.isfinite(loc.homography).all()
    assert np.isfinite(loc.homography_inv).all()


def test_locator_v31_roi_offset_is_global_coordinates():
    payload = b"locator-v31-roi"
    header = FrameHeaderBasic.make(
        frame_type=FRAME_DATA,
        session_id=2,
        epoch_id=0,
        frame_id=1,
        total_frames=1,
        chunk_id=0,
        payload=payload,
    )
    frame = encode_frame_basic(header=header, payload=payload, width=1280, height=720)
    loc_full = locate_frame(frame, config=LocatorConfig(grid_w=160, grid_h=96))
    assert not isinstance(loc_full, LocateError)
    bx0 = int(np.min(loc_full.quad_src[:, 0]))
    by0 = int(np.min(loc_full.quad_src[:, 1]))
    bw = int(np.max(loc_full.quad_src[:, 0]) - bx0)
    bh = int(np.max(loc_full.quad_src[:, 1]) - by0)

    roi = (max(0, bx0 - 80), max(0, by0 - 80), bw + 160, bh + 160)
    loc_roi = locate_frame(frame, search_roi=roi, config=LocatorConfig(grid_w=160, grid_h=96))
    assert not isinstance(loc_roi, LocateError)
    # quad in ROI mode must still be in global frame coordinates
    assert int(np.min(loc_roi.quad_src[:, 0])) >= roi[0]
    assert int(np.min(loc_roi.quad_src[:, 1])) >= roi[1]
