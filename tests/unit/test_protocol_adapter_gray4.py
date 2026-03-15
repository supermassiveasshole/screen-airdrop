from __future__ import annotations

from screen_airdrop.common.protocol_basic import FRAME_DATA, FRAME_SYNC, FrameHeaderBasic
from screen_airdrop.sender.protocol_adapter_gray4 import Gray4ProtocolEncoder


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


def test_gray4_data_masks_vary_by_epoch_and_chunk():
    header_a = _make_header(frame_type=FRAME_DATA, epoch_id=0, chunk_id=10)
    header_b = _make_header(frame_type=FRAME_DATA, epoch_id=1, chunk_id=10)
    header_c = _make_header(frame_type=FRAME_DATA, epoch_id=0, chunk_id=11)

    assert Gray4ProtocolEncoder._select_mask(header_a, None) == 2
    assert Gray4ProtocolEncoder._select_mask(header_b, None) == 3
    assert Gray4ProtocolEncoder._select_mask(header_c, None) == 3


def test_gray4_non_data_frames_keep_stable_mask():
    sync_header = _make_header(frame_type=FRAME_SYNC, epoch_id=5, chunk_id=0)

    assert Gray4ProtocolEncoder._select_mask(sync_header, None) == 3


def test_gray4_forced_mask_overrides_auto_selection():
    header = _make_header(frame_type=FRAME_DATA, epoch_id=7, chunk_id=99)

    assert Gray4ProtocolEncoder._select_mask(header, 5) == 5


def test_gray4_data_masks_vary_by_frame_id_for_same_chunk():
    header_a = _make_header(frame_type=FRAME_DATA, epoch_id=2, chunk_id=40, frame_id=10)
    header_b = _make_header(frame_type=FRAME_DATA, epoch_id=2, chunk_id=40, frame_id=11)

    assert Gray4ProtocolEncoder._select_mask(header_a, None) != Gray4ProtocolEncoder._select_mask(
        header_b, None
    )
