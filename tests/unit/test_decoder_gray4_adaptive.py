import numpy as np

from screen_airdrop.receiver.transport.gray4.decoder import (
    _base_sample_phase_candidates,
    _fit_gray4_centers,
    _quantize_gray4_adaptive,
)
from screen_airdrop.sender.transport.gray4.encoder import build_layout_gray4


def test_fit_gray4_centers_tracks_shifted_levels():
    layout = build_layout_gray4(grid_w=32, grid_h=24, guard_band=1, corner_size=7)
    avg = np.zeros((layout.frame_h, layout.frame_w), dtype=np.uint8)
    shifted = [18, 96, 162, 232]
    for index, (x, y) in enumerate(layout.data_coords):
        avg[y, x] = shifted[index % 4]

    centers = _fit_gray4_centers(avg, layout)

    assert centers.shape == (4,)
    assert centers[0] < centers[1] < centers[2] < centers[3]
    assert abs(float(centers[0]) - shifted[0]) < 12.0
    assert abs(float(centers[3]) - shifted[3]) < 12.0


def test_quantize_gray4_adaptive_uses_fitted_centers():
    centers = np.array([20.0, 95.0, 165.0, 235.0], dtype=np.float32)
    symbol, conf = _quantize_gray4_adaptive(156, centers)

    assert symbol == 2
    assert conf > 0.5


def test_base_sample_phase_candidates_includes_zero_phi_and_locator_phi():
    candidates = _base_sample_phase_candidates(0.12, -0.07)

    assert (0.0, 0.0) in candidates
    assert any(abs(px - 0.12) < 1e-6 and abs(py + 0.07) < 1e-6 for px, py in candidates)
    assert len(candidates) == 2
    assert all(-0.35 <= px <= 0.35 and -0.35 <= py <= 0.35 for px, py in candidates)
