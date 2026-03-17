# pyright: reportAttributeAccessIssue=false
import importlib.util
import json
from pathlib import Path


def _load_module(module_name: str, rel_path: str):
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / rel_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_summarize_renders_debug_snapshot_analysis_table(tmp_path):
    module = _load_module("bench_summarize", "bench/summarize.py")
    result_root = tmp_path / "results"
    result_root.mkdir()
    (result_root / "debug_snapshot_analysis_123.json").write_text(
        json.dumps(
            [
                {
                    "benchmark_kind": "debug_snapshot_analysis",
                    "label": "gray4_case",
                    "total_frames": 100,
                    "failure_rate": 0.12,
                    "data_failure_rate": 0.15,
                    "control_failure_rate": 0.0,
                    "primary_decode_error": "crc_failed",
                }
            ]
        ),
        encoding="utf-8",
    )

    original_root = module.RESULT_ROOT
    try:
        module.RESULT_ROOT = result_root
        exit_code = module.main()
    finally:
        module.RESULT_ROOT = original_root

    assert exit_code == 0
    summary_md = (result_root / "summary.md").read_text(encoding="utf-8")
    assert "## Debug Snapshot Analysis" in summary_md
    assert "gray4_case" in summary_md
    assert "crc_failed" in summary_md
