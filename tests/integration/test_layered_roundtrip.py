"""Integration tests for layered encoder/decoder roundtrip."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from screen_airdrop.common.protocol_basic import FrameHeaderBasic
from screen_airdrop.common.protocol_layered import LAYERED_BOOTSTRAP_ROWS
from screen_airdrop.receiver.decoder_layered import decode_frame_layered
from screen_airdrop.sender.encoder_layered import (
    build_layout_layered,
    encode_frame_layered,
    frame_capacity_bytes_layered,
)


def test_layered_encoder_decoder_roundtrip():
    grid_w = 224
    grid_h = 136
    capacity = frame_capacity_bytes_layered(grid_w=grid_w, grid_h=grid_h, guard_band=1, corner_size=7)
    assert capacity > 0
    payload = bytes(range(min(capacity, 200)))
    header = FrameHeaderBasic.make(
        frame_type=1,
        session_id=1234,
        epoch_id=2,
        frame_id=3,
        total_frames=9,
        chunk_id=5,
        payload=payload,
    )
    frame = encode_frame_layered(
        header,
        payload,
        width=1920,
        height=1080,
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=1,
        corner_size=7,
    )
    decoded_header, decoded_payload, _meta = decode_frame_layered(
        frame,
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=1,
        corner_size=7,
    )
    assert decoded_header.session_id == header.session_id
    assert decoded_header.epoch_id == header.epoch_id
    assert decoded_header.frame_id == header.frame_id
    assert decoded_header.total_frames == header.total_frames
    assert decoded_header.chunk_id == header.chunk_id
    assert decoded_payload == payload


def test_layered_roundtrip_survives_top_band_brightness_shift():
    grid_w = 224
    grid_h = 136
    payload = bytes(range(96))
    header = FrameHeaderBasic.make(
        frame_type=1,
        session_id=1234,
        epoch_id=2,
        frame_id=3,
        total_frames=9,
        chunk_id=5,
        payload=payload,
    )
    frame = encode_frame_layered(
        header,
        payload,
        width=1920,
        height=1080,
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=1,
        corner_size=7,
    )
    layout = build_layout_layered(grid_w=grid_w, grid_h=grid_h, guard_band=1, corner_size=7)
    shifted = frame.copy().astype("int16")
    top_limit = layout.base.grid_y0 + 12
    shifted[:top_limit, :] = shifted[:top_limit, :] - 22
    shifted = shifted.clip(0, 255).astype("uint8")
    decoded_header, decoded_payload, _meta = decode_frame_layered(
        shifted,
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=1,
        corner_size=7,
    )
    assert decoded_header.session_id == header.session_id
    assert decoded_payload == payload


@pytest.mark.parametrize(
    ("name", "transform"),
    [
        (
            "brightness_shift",
            lambda band: np.clip(band.astype(np.int16) - 22, 0, 255).astype(np.uint8),
        ),
        (
            "mild_blur",
            lambda band: cv2.GaussianBlur(band, (5, 5), 0),
        ),
        (
            "light_noise",
            lambda band: np.clip(
                band.astype(np.int16)
                + np.random.default_rng(1234).integers(-8, 9, size=band.shape, dtype=np.int16),
                0,
                255,
            ).astype(np.uint8),
        ),
        (
            "blur_plus_shift",
            lambda band: np.clip(
                cv2.GaussianBlur(band, (5, 5), 0).astype(np.int16) - 16,
                0,
                255,
            ).astype(np.uint8),
        ),
    ],
)
def test_layered_roundtrip_survives_mild_control_band_perturbations(name, transform):
    del name
    grid_w = 224
    grid_h = 136
    payload = bytes(range(96))
    header = FrameHeaderBasic.make(
        frame_type=1,
        session_id=1234,
        epoch_id=2,
        frame_id=3,
        total_frames=9,
        chunk_id=5,
        payload=payload,
    )
    frame = encode_frame_layered(
        header,
        payload,
        width=1920,
        height=1080,
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=1,
        corner_size=7,
    )
    layout = build_layout_layered(grid_w=grid_w, grid_h=grid_h, guard_band=1, corner_size=7)
    perturbed = frame.copy()
    top_limit = layout.base.grid_y0 + LAYERED_BOOTSTRAP_ROWS
    perturbed[:top_limit, :] = transform(perturbed[:top_limit, :])
    decoded_header, decoded_payload, _meta = decode_frame_layered(
        perturbed,
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=1,
        corner_size=7,
    )
    assert decoded_header.session_id == header.session_id
    assert decoded_payload == payload
