import importlib.util
import json
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "bench" / "evaluate_header_ecc_candidates.py"
    spec = importlib.util.spec_from_file_location("evaluate_header_ecc_candidates", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_writes_json(monkeypatch, tmp_path, capsys):
    module = _load_module()

    def _fake_evaluate_frame(path, grid_w, grid_h, mask_id, repetition):
        return {
            "file": Path(path).name,
            "grid": f"{grid_w}x{grid_h}",
            "mask_id": mask_id,
            "repetition": repetition,
            "candidates": {"baseline": {"ok": False}},
        }

    monkeypatch.setattr(module, "evaluate_frame", _fake_evaluate_frame)
    output_path = tmp_path / "header-ecc.json"

    rc = module.main(
        [
            "--module-grid",
            "240x144",
            "--frames",
            "a.npy",
            "b.npy",
            "--mask-id",
            "3",
            "--repetition",
            "1",
            "--output-json",
            str(output_path),
        ]
    )

    assert rc == 0
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert [item["file"] for item in data] == ["a.npy", "b.npy"]
    assert "240x144" in capsys.readouterr().out
