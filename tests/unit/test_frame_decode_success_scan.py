from pathlib import Path

from bench.scan_frame_decode_success import (
    _candidate_cases,
    _materialize_case,
    _screen_runbook,
    _select_candidates,
)


def test_materialized_case_creates_small_sample_file():
    case = _candidate_cases(
        ecc_level="Q",
        fps=12,
        capture_fps=30,
        benchmark_seconds=12,
        sample_chunks=8,
        compact_grids=[(166, 102)],
        payload_ratios=[0.9],
        display_modes=["fullscreen"],
    )[1]
    realized = _materialize_case(case)
    path = Path(realized["sample_file"])
    assert path.exists()
    assert path.stat().st_size == realized["sample_bytes"]


def test_screen_runbook_uses_sample_file_and_payload_ratio():
    case = _candidate_cases(
        ecc_level="Q",
        fps=12,
        capture_fps=30,
        benchmark_seconds=12,
        sample_chunks=8,
        compact_grids=[(166, 102)],
        payload_ratios=[0.85],
        display_modes=["large"],
    )[1]
    realized = _materialize_case(case)
    runbook = _screen_runbook(realized)
    assert runbook["payload_ratio"] == 0.85
    assert realized["sample_file"] in runbook["sender_command"]
    assert "--frame-width 1600 --frame-height 900" in runbook["sender_command"]


def test_select_candidates_prefers_success_then_margin():
    results = [
        {
            "protocol": "compact",
            "display_mode": "fullscreen",
            "module_grid": "166x102",
            "payload_ratio": 0.95,
            "decode_success_rate": 0.98,
            "goodput_kib_per_s": 8.0,
            "cap_fps": 15.0,
            "dec_fps": 14.0,
            "bad_frame_rate": 0.05,
            "locator_fail_rate": 0.02,
            "exit_code": 0,
        },
        {
            "protocol": "compact",
            "display_mode": "fullscreen",
            "module_grid": "180x110",
            "payload_ratio": 0.85,
            "decode_success_rate": 0.97,
            "goodput_kib_per_s": 7.9,
            "cap_fps": 15.5,
            "dec_fps": 14.5,
            "bad_frame_rate": 0.02,
            "locator_fail_rate": 0.01,
            "exit_code": 0,
        },
    ]
    selected = _select_candidates(results)
    assert selected["best_decode_success"] is not None
    assert selected["best_margin"] is not None
    assert selected["best_decode_success"]["module_grid"] == "166x102"
    assert selected["best_margin"]["module_grid"] == "180x110"
