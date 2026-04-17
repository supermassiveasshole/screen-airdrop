from __future__ import annotations

from screen_airdrop.common.transport.protocol_basic import (
    FRAME_DATA,
    FRAME_END,
    FRAME_SYNC,
    FrameHeaderBasic,
)
from screen_airdrop.sender.transport.gray4.adapter import Gray4ProtocolEncoder


def _make_header(*, frame_type: int, epoch_id: int, chunk_id: int, frame_id: int = 0) -> FrameHeaderBasic:
    return FrameHeaderBasic.make(
        frame_type=frame_type,
        session_id=1,
        epoch_id=epoch_id,
        frame_id=frame_id,
        total_frames=10,
        chunk_id=chunk_id,
        payload=b"",
    )


def test_gray4_data_masks_are_deterministic_for_same_header():
    encoder = Gray4ProtocolEncoder(grid_w=224, grid_h=136, ecc_level="L")
    header = _make_header(frame_type=FRAME_DATA, epoch_id=0, chunk_id=10)

    mask_a = encoder._select_mask(header, None)
    mask_b = encoder._select_mask(header, None)

    assert mask_a == mask_b
    assert 0 <= mask_a <= 7


def test_gray4_data_masks_vary_by_epoch_and_chunk():
    encoder = Gray4ProtocolEncoder(grid_w=224, grid_h=136, ecc_level="L")
    header_a = _make_header(frame_type=FRAME_DATA, epoch_id=0, chunk_id=10)
    header_b = _make_header(frame_type=FRAME_DATA, epoch_id=1, chunk_id=10)
    header_c = _make_header(frame_type=FRAME_DATA, epoch_id=0, chunk_id=11)

    masks = {
        encoder._select_mask(header_a, None),
        encoder._select_mask(header_b, None),
        encoder._select_mask(header_c, None),
    }

    assert all(0 <= mask <= 7 for mask in masks)
    assert len(masks) >= 2


def test_gray4_sync_frames_vary_mask_by_frame_id():
    encoder = Gray4ProtocolEncoder(grid_w=224, grid_h=136, ecc_level="L")
    sync_a = _make_header(frame_type=FRAME_SYNC, epoch_id=5, chunk_id=0, frame_id=0)
    sync_b = _make_header(frame_type=FRAME_SYNC, epoch_id=5, chunk_id=0, frame_id=3)

    assert encoder._select_mask(sync_a, None) == 0
    assert encoder._select_mask(sync_b, None) == 2


def test_gray4_sync_frames_cover_four_masks_twice_each():
    encoder = Gray4ProtocolEncoder(grid_w=224, grid_h=136, ecc_level="L")

    masks = [
        encoder._select_mask(
            _make_header(frame_type=FRAME_SYNC, epoch_id=5, chunk_id=0, frame_id=frame_id),
            None,
        )
        for frame_id in range(8)
    ]

    assert masks == [0, 0, 2, 2, 4, 4, 6, 6]


def test_gray4_non_sync_control_frames_keep_stable_mask():
    encoder = Gray4ProtocolEncoder(grid_w=224, grid_h=136, ecc_level="L")
    end_header = _make_header(frame_type=FRAME_END, epoch_id=5, chunk_id=0)

    assert encoder._select_mask(end_header, None) == 3


def test_gray4_control_data_frames_keep_stable_mask():
    encoder = Gray4ProtocolEncoder(grid_w=224, grid_h=136, ecc_level="L")
    manifest_header = _make_header(frame_type=FRAME_DATA, epoch_id=1, chunk_id=0, frame_id=7)
    session_header = _make_header(
        frame_type=FRAME_DATA, epoch_id=1, chunk_id=0xFFFFFFFD, frame_id=9
    )

    assert encoder._select_mask(manifest_header, None) == 3
    assert encoder._select_mask(session_header, None) == 3


def test_gray4_forced_mask_overrides_auto_selection():
    encoder = Gray4ProtocolEncoder(grid_w=224, grid_h=136, ecc_level="L")
    header = _make_header(frame_type=FRAME_DATA, epoch_id=7, chunk_id=99)

    assert encoder._select_mask(header, 5) == 5


def test_gray4_data_masks_vary_by_frame_id_for_same_chunk():
    encoder = Gray4ProtocolEncoder(grid_w=224, grid_h=136, ecc_level="L")
    header_a = _make_header(frame_type=FRAME_DATA, epoch_id=2, chunk_id=40, frame_id=10)
    header_b = _make_header(frame_type=FRAME_DATA, epoch_id=2, chunk_id=40, frame_id=11)

    mask_a = encoder._select_mask(header_a, None)
    mask_b = encoder._select_mask(header_b, None)

    assert 0 <= mask_a <= 7
    assert 0 <= mask_b <= 7
    assert mask_a != mask_b
