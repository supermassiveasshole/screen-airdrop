import importlib.util
import json
import sys
from pathlib import Path


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


def _write_debug_dir(path: Path, *, plane: str, decode_error: str) -> None:
    path.mkdir()
    (path / "summary.json").write_text(
        json.dumps(
            {
                "total_frames": 1,
                "planes": {plane: 1},
                "control_kinds": {"layout": 1} if plane == "control" else {},
                "protocol_paths": {"gray4": 1},
            }
        ),
        encoding="utf-8",
    )
    (path / "index_all.jsonl").write_text(
        json.dumps(
            {
                "frame_index": 1,
                "plane": plane,
                "control_family": "bootstrap" if plane == "control" else "",
                "control_kind": "layout" if plane == "control" else "",
                "protocol_path_used": "gray4",
                "decode_error": decode_error,
                "frame_json": "frame_00001.json",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_compare_debug_snapshots_main_writes_analysis_json(tmp_path, capsys):
    module = _load_module("compare_debug_snapshots", "bench/compare_debug_snapshots.py")
    debug_a = tmp_path / "debug_a"
    debug_b = tmp_path / "debug_b"
    _write_debug_dir(debug_a, plane="data", decode_error="crc_failed")
    _write_debug_dir(debug_b, plane="control", decode_error="")
    out_path = tmp_path / "analysis.json"

    exit_code = module.main(
        [
            "--debug-dirs",
            str(debug_a),
            str(debug_b),
            "--labels",
            "data_case,control_case",
            "--output-json",
            str(out_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(payload) == 2
    assert payload[0]["label"] == "data_case"
    assert payload[0]["primary_decode_error"] == "crc_failed"
    assert payload[0]["data_failure_rate"] == 1.0
    assert payload[1]["label"] == "control_case"
    assert payload[1]["control_failure_rate"] == 0.0

    stdout = capsys.readouterr().out
    assert "analysis.json" in stdout
