"""Test protocol interface and basic adapter."""

from unittest.mock import patch

import numpy as np
import pytest

from screen_airdrop.common.protocol_basic import FRAME_DATA, FrameHeaderBasic
from screen_airdrop.common.protocol_interface import DecodedFrame
from screen_airdrop.receiver.decoder_basic import DecodeMetaBasic
from screen_airdrop.receiver.decoder_compact import decode_frame_compact
from screen_airdrop.receiver.detector_basic import _bbox_from_non_black
from screen_airdrop.receiver.protocol_adapter_basic import BasicProtocolDecoder
from screen_airdrop.receiver.protocol_adapter_compact import CompactProtocolDecoder
from screen_airdrop.sender.protocol_adapter_basic import BasicProtocolEncoder
from screen_airdrop.sender.protocol_adapter_compact import CompactProtocolEncoder


def test_basic_encoder_adapter():
    """Test BasicProtocolEncoder wraps existing encoder correctly."""
    encoder = BasicProtocolEncoder(grid_w=160, grid_h=96, ecc_level="Q")

    # Check layout info
    layout = encoder.get_layout()
    assert layout.protocol_name == "basic"
    assert layout.grid_w == 160
    assert layout.grid_h == 96
    assert layout.bits_per_module == 1

    # Encode a frame
    header = FrameHeaderBasic.make(
        frame_type=FRAME_DATA,
        session_id=42,
        epoch_id=0,
        frame_id=1,
        total_frames=10,
        chunk_id=1,
        payload=b"test",
    )
    img = encoder.encode_frame(header, b"test", 1920, 1080)

    assert img.shape[2] == 3  # BGR
    assert img.dtype == np.uint8


def test_basic_decoder_adapter():
    """Test BasicProtocolDecoder wraps existing decoder correctly."""
    decoder = BasicProtocolDecoder(grid_w=160, grid_h=96)

    # Check layout info
    layout = decoder.get_layout()
    assert layout.protocol_name == "basic"
    assert layout.grid_w == 160
    assert layout.grid_h == 96
    assert layout.data_capacity_bits > 0


def test_basic_encoder_passes_typed_header_through():
    encoder = BasicProtocolEncoder(grid_w=160, grid_h=96, ecc_level="L")
    payload = b"phase0-roundtrip"
    header = FrameHeaderBasic.make(
        frame_type=FRAME_DATA,
        session_id=7,
        epoch_id=1,
        frame_id=2,
        total_frames=10,
        chunk_id=3,
        payload=payload,
    )
    fake_image = np.zeros((32, 32, 3), dtype=np.uint8)

    with patch(
        "screen_airdrop.sender.protocol_adapter_basic.encode_frame_basic",
        return_value=fake_image,
    ) as mocked_encode:
        image = encoder.encode_frame(header, payload, 1920, 1080)

    assert image is fake_image
    assert mocked_encode.call_args.kwargs["header"] is header
    assert mocked_encode.call_args.kwargs["payload"] == payload


def test_basic_decoder_preserves_typed_result():
    decoder = BasicProtocolDecoder(grid_w=160, grid_h=96)
    header = FrameHeaderBasic.make(
        frame_type=FRAME_DATA,
        session_id=9,
        epoch_id=1,
        frame_id=5,
        total_frames=20,
        chunk_id=4,
        payload=b"payload",
    )
    meta = DecodeMetaBasic(
        protocol_version_used=31,
        locator_engine="auto",
        confidence=0.9,
        fail_reason="",
        elapsed_ms=4.0,
        legacy_used=False,
        homography_rmse=1.5,
        rs_corrected_symbols=2,
        crc_ok=True,
        mask_id=3,
        grid_size="160x96",
        det_bbox=(10, 20, 30, 40),
        decode_attempts=2,
        det_confidence=0.9,
        new_fail_reason="",
        new_elapsed_ms=4.0,
        legacy_elapsed_ms=0.0,
        locator_debug_artifacts={"kept": True},
        locator_warped_preview=None,
    )

    with patch(
        "screen_airdrop.receiver.protocol_adapter_basic.decode_frame_basic",
        return_value=(header, b"payload", meta),
    ):
        decoded = decoder.decode_frame(np.zeros((32, 32, 3), dtype=np.uint8))

    assert isinstance(decoded, DecodedFrame)
    assert decoded.frame_header is header
    assert decoded.payload == b"payload"
    assert decoded.meta is meta


def test_compact_encoder_decoder_roundtrip():
    encoder = CompactProtocolEncoder(grid_w=160, grid_h=96, ecc_level="L")
    decoder = CompactProtocolDecoder(grid_w=160, grid_h=96)
    payload = b"compact-roundtrip"
    header = FrameHeaderBasic.make(
        frame_type=FRAME_DATA,
        session_id=11,
        epoch_id=1,
        frame_id=6,
        total_frames=20,
        chunk_id=5,
        payload=payload,
    )

    frame = encoder.encode_frame(header, payload, 1920, 1080)
    decoded = decoder.decode_frame(frame)

    assert decoded.frame_header.session_id == header.session_id
    assert decoded.frame_header.frame_id == header.frame_id
    assert decoded.frame_header.chunk_id == header.chunk_id
    assert decoded.payload == payload
    assert decoded.meta.locator_engine == "legacy"  # Compact uses legacy locator for 7x7 finders


@pytest.mark.parametrize("ecc_level", ["L", "M", "Q", "H"])
def test_basic_encoder_decoder_roundtrip_all_ecc_levels(ecc_level: str):
    encoder = BasicProtocolEncoder(grid_w=160, grid_h=96, ecc_level=ecc_level)
    decoder = BasicProtocolDecoder(grid_w=160, grid_h=96)
    payload = f"basic-roundtrip-{ecc_level}".encode("ascii")
    header = FrameHeaderBasic.make(
        frame_type=FRAME_DATA,
        session_id=21,
        epoch_id=1,
        frame_id=3,
        total_frames=20,
        chunk_id=8,
        payload=payload,
    )

    frame = encoder.encode_frame(header, payload, 1920, 1080)
    decoded = decoder.decode_frame(frame)

    assert decoded.frame_header.session_id == header.session_id
    assert decoded.frame_header.frame_id == header.frame_id
    assert decoded.frame_header.chunk_id == header.chunk_id
    assert decoded.payload == payload


@pytest.mark.parametrize("ecc_level", ["L", "M", "Q", "H"])
def test_compact_encoder_decoder_roundtrip_all_ecc_levels(ecc_level: str):
    encoder = CompactProtocolEncoder(grid_w=160, grid_h=96, ecc_level=ecc_level)
    decoder = CompactProtocolDecoder(grid_w=160, grid_h=96)
    payload = f"compact-roundtrip-{ecc_level}".encode("ascii")
    header = FrameHeaderBasic.make(
        frame_type=FRAME_DATA,
        session_id=22,
        epoch_id=1,
        frame_id=4,
        total_frames=20,
        chunk_id=9,
        payload=payload,
    )

    frame = encoder.encode_frame(header, payload, 1920, 1080)
    decoded = decoder.decode_frame(frame)

    assert decoded.frame_header.session_id == header.session_id
    assert decoded.frame_header.frame_id == header.frame_id
    assert decoded.frame_header.chunk_id == header.chunk_id
    assert decoded.payload == payload


def test_compact_decodes_tight_manual_roi_with_white_border_trimmed():
    encoder = CompactProtocolEncoder(grid_w=160, grid_h=96, ecc_level="L")
    payload = b"tight-roi-roundtrip"
    header = FrameHeaderBasic.make(
        frame_type=FRAME_DATA,
        session_id=12,
        epoch_id=1,
        frame_id=7,
        total_frames=20,
        chunk_id=6,
        payload=payload,
    )

    frame = encoder.encode_frame(header, payload, 1920, 1080)
    bbox = _bbox_from_non_black(frame)
    assert bbox is not None
    x, y, w, h = bbox
    trim = 8
    cropped = frame[y + trim : y + h - trim, x + trim : x + w - trim].copy()

    decoded_header, decoded_payload, meta = decode_frame_compact(
        frame=cropped,
        detect_mode="track",
        forced_roi=(0, 0, cropped.shape[1], cropped.shape[0]),
        roi_only=True,
        manual_strict=True,
        locator_engine="auto",
    )

    assert decoded_header.session_id == header.session_id
    assert decoded_header.frame_id == header.frame_id
    assert decoded_header.chunk_id == header.chunk_id
    assert decoded_payload == payload
    assert meta.locator_engine == "legacy"
