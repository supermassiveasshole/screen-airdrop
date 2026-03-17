# pyright: reportAttributeAccessIssue=false
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np


def _load_module(module_name: str, rel_path: str):
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / rel_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_case_specs_include_clean_and_blur():
    module = _load_module("gray4_perturbation_benchmark", "bench/gray4_perturbation_benchmark.py")
    names = [item["name"] for item in module._case_specs()]
    assert "clean" in names
    assert "gaussian_blur_3" in names


def test_write_frames_applies_transform(tmp_path):
    module = _load_module("gray4_perturbation_benchmark", "bench/gray4_perturbation_benchmark.py")
    src_frames = [("000000.npy", np.full((8, 8, 3), 32, dtype=np.uint8))]
    out_dir = tmp_path / "frames"

    module._write_frames(out_dir, src_frames, lambda frame: np.clip(frame + 10, 0, 255).astype(np.uint8))

    written = np.load(out_dir / "000000.npy")
    assert int(written[0, 0, 0]) == 42


def test_main_filters_cases_and_writes_json(tmp_path):
    module = _load_module("gray4_perturbation_benchmark", "bench/gray4_perturbation_benchmark.py")
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    np.save(frames_dir / "000000.npy", np.zeros((16, 16, 3), dtype=np.uint8))
    output_json = tmp_path / "out.json"

    original_run_case = module._run_case
    try:
        module._run_case = lambda **kwargs: {
            "benchmark_kind": "gray4_perturbation",
            "case": kwargs["case_name"],
            "failure_rate": 0.0,
        }
        exit_code = module.main(
            [
                "--frames-dir",
                str(frames_dir),
                "--cases",
                "clean,gamma_0p85",
                "--output-json",
                str(output_json),
            ]
        )
    finally:
        module._run_case = original_run_case

    assert exit_code == 0
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert [item["case"] for item in payload] == ["clean", "gamma_0p85"]
