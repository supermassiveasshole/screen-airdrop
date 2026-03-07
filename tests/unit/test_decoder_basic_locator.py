import pytest

from screen_airdrop.common.protocol_basic import FRAME_DATA, FrameHeaderBasic
from screen_airdrop.receiver.decoder_basic import decode_frame_basic
from screen_airdrop.sender.encoder_basic import encode_frame_basic


def _build_frame(payload: bytes = b"locator-engine"):
    header = FrameHeaderBasic.make(
        frame_type=FRAME_DATA,
        session_id=99,
        epoch_id=1,
        frame_id=2,
        total_frames=3,
        chunk_id=1,
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
    return header, frame


def test_decode_v31_locator_engine_new():
    header, frame = _build_frame(b"engine-new")
    parsed, restored, meta = decode_frame_basic(frame=frame, locator_engine="new")
    assert parsed.chunk_id == header.chunk_id
    assert restored == b"engine-new"
    assert meta.locator_engine == "new"
    assert meta.legacy_used is False


def test_decode_v31_locator_engine_legacy():
    header, frame = _build_frame(b"engine-legacy")
    parsed, restored, meta = decode_frame_basic(frame=frame, locator_engine="legacy")
    assert parsed.chunk_id == header.chunk_id
    assert restored == b"engine-legacy"
    assert meta.locator_engine == "legacy"
    assert meta.legacy_used is True


def test_decode_v31_locator_engine_auto_fallback_to_legacy():
    header, frame = _build_frame(b"engine-auto-fallback")
    parsed, restored, meta = decode_frame_basic(
        frame=frame,
        locator_engine="auto",
        locator_confidence_threshold=1.1,
    )
    assert parsed.chunk_id == header.chunk_id
    assert restored == b"engine-auto-fallback"
    assert meta.locator_engine == "legacy"
    assert meta.legacy_used is True
    assert meta.new_fail_reason != ""


def test_decode_v31_locator_engine_new_respects_threshold():
    header, frame = _build_frame(b"engine-new-thr")
    parsed, restored, _meta = decode_frame_basic(
        frame=frame,
        locator_engine="new",
        locator_confidence_threshold=1.1,
    )
    assert parsed.chunk_id == header.chunk_id
    assert restored == b"engine-new-thr"


def test_decode_v31_full_mode_ignores_forced_roi():
    header, frame = _build_frame(b"engine-full-ignore-roi")
    parsed, restored, _meta = decode_frame_basic(
        frame=frame,
        detect_mode="full",
        forced_roi=(0, 0, 64, 64),
        locator_engine="new",
    )
    assert parsed.chunk_id == header.chunk_id
    assert restored == b"engine-full-ignore-roi"


def test_decode_v31_manual_strict_requires_forced_roi():
    _header, frame = _build_frame(b"engine-manual-strict")
    with pytest.raises(ValueError, match="requires forced_roi"):
        decode_frame_basic(
            frame=frame,
            detect_mode="track",
            manual_strict=True,
            forced_roi=None,
            locator_engine="new",
        )
