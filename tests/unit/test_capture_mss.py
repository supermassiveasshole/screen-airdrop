import numpy as np

from screen_airdrop.receiver.capture_mss import compute_frame_diff, screenshot_to_bgr


class _FakeShot:
    def __init__(self, arr: np.ndarray):
        self._arr = arr

    @property
    def __array_interface__(self):
        return self._arr.__array_interface__


def test_screenshot_to_bgr_copies_only_first_three_channels():
    src = np.arange(2 * 3 * 4, dtype=np.uint8).reshape(2, 3, 4)
    frame = screenshot_to_bgr(_FakeShot(src))

    assert frame.shape == (2, 3, 3)
    assert np.array_equal(frame, src[:, :, :3])

    src[0, 0, 0] = 255
    assert frame[0, 0, 0] != 255


def test_compute_frame_diff_zero_for_same_frame():
    frame = np.zeros((16, 16, 3), dtype=np.uint8)
    assert compute_frame_diff(frame, frame.copy()) == 0.0


def test_compute_frame_diff_positive_for_changed_frame():
    frame = np.zeros((16, 16, 3), dtype=np.uint8)
    prev = frame.copy()
    frame[::4, ::4] = 255
    assert compute_frame_diff(frame, prev) > 0.0
