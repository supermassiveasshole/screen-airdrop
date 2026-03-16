import numpy as np

from screen_airdrop.receiver.control_decode import (
    _try_unpack_candidates,
    decode_binary_control_header,
)


def test_decode_binary_control_header_tries_threshold_candidates():
    data_coords = [(i, 0) for i in range(8)]
    avg_gray_u8 = np.array([[100, 160, 100, 160, 100, 160, 100, 160]], dtype=np.uint8)
    header_map = (avg_gray_u8 >= 170).astype(np.uint8)

    decoded = decode_binary_control_header(
        avg_gray_u8=avg_gray_u8,
        header_maps=[header_map],
        sample_stack_u8=np.stack([avg_gray_u8 for _ in range(9)], axis=0),
        thresholds=[128],
        data_coords=data_coords,
        header_size_bytes=1,
        repetition=1,
        mask_id=0,
        mask_bit_fn=lambda _mask_id, _x, _y: 0,
        unpack_header=lambda data: data if data == bytes([0b01010101]) else (_ for _ in ()).throw(ValueError("bad")),
    )

    assert decoded == bytes([0b01010101])


def test_decode_binary_control_header_recovers_single_low_confidence_bit():
    data_coords = [(i, 0) for i in range(8)]
    avg_gray_u8 = np.array([[120, 160, 100, 160, 100, 160, 100, 160]], dtype=np.uint8)
    header_map = (avg_gray_u8 >= 128).astype(np.uint8)
    sample_stack = np.stack([avg_gray_u8 for _ in range(9)], axis=0)
    sample_stack[:, 0, 0] = np.array([120, 120, 120, 120, 120, 160, 160, 160, 160], dtype=np.uint8)

    decoded = decode_binary_control_header(
        avg_gray_u8=avg_gray_u8,
        header_maps=[header_map],
        sample_stack_u8=sample_stack,
        thresholds=[128],
        data_coords=data_coords,
        header_size_bytes=1,
        repetition=1,
        mask_id=0,
        mask_bit_fn=lambda _mask_id, _x, _y: 0,
        unpack_header=lambda data: data if data == bytes([0b01010101]) else (_ for _ in ()).throw(ValueError("bad")),
    )

    assert decoded == bytes([0b01010101])


def test_try_unpack_candidates_supports_three_bit_recovery_when_requested():
    decoded = _try_unpack_candidates(
        base_scores=[-0.1, 0.1, -0.1, -5.0, -5.0, -5.0, -5.0, -5.0],
        header_size_bytes=1,
        unpack_header=lambda data: data if data == bytes([0b11100000]) else (_ for _ in ()).throw(ValueError("bad")),
        max_uncertain=4,
        max_flips=3,
    )
    assert decoded == bytes([0b11100000])
