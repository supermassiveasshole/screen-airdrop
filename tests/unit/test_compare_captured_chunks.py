import importlib.util
import json
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "bench" / "compare_captured_chunks.py"
    spec = importlib.util.spec_from_file_location("compare_captured_chunks", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_missing_chunks_from_report_json(tmp_path):
    module = _load_module()
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps({"missing_chunk_ids": [10, 47, 77, 170]}),
        encoding="utf-8",
    )

    parser = module.build_parser()
    args = parser.parse_args(
        [
            "--sender-dir",
            str(tmp_path / "sender"),
            "--captured-dir",
            str(tmp_path / "captured"),
            "--protocol",
            "gray4",
            "--module-grid",
            "240x144",
            "--report-json",
            str(report_path),
        ]
    )

    assert module._parse_missing_chunks(args) == [10, 47, 77, 170]


def test_chunk_to_files_collects_successful_records():
    module = _load_module()
    mapping = module._chunk_to_files(
        [
            {"ok": True, "chunk_id": 10, "file": "a.png"},
            {"ok": False, "file": "b.png", "error": "bad header"},
            {"ok": True, "chunk_id": 10, "file": "c.png"},
            {"ok": True, "chunk_id": 47, "file": "d.png"},
        ]
    )

    assert mapping == {10: ["a.png", "c.png"], 47: ["d.png"]}


def test_compare_dirs_includes_neighbor_chunks(monkeypatch, tmp_path):
    module = _load_module()

    sender_records = [
        {"ok": True, "chunk_id": 9, "file": "s9.png", "frame_id": 40},
        {"ok": True, "chunk_id": 10, "file": "s10.png", "frame_id": 41},
        {"ok": True, "chunk_id": 11, "file": "s11.png", "frame_id": 42},
    ]
    captured_records = [
        {"ok": True, "chunk_id": 9, "file": "c9.npy", "frame_id": 40},
        {"ok": True, "chunk_id": 11, "file": "c11.npy", "frame_id": 42},
    ]

    def _fake_decode_dir(frames_dir, protocol, grid_w, grid_h):
        if "sender" in str(frames_dir):
            return sender_records
        return captured_records

    monkeypatch.setattr(module, "_decode_dir", _fake_decode_dir)

    summary = module.compare_dirs(
        sender_dir=tmp_path / "sender",
        captured_dir=tmp_path / "captured",
        protocol="gray4",
        grid_w=240,
        grid_h=144,
        missing_chunks=[10],
        neighbor_window=1,
    )

    assert summary["captured_missing_chunks"] == [10]
    assert summary["neighbor_chunks"]["10"]["9"]["sender_files"] == ["s9.png"]
    assert summary["neighbor_chunks"]["10"]["10"]["captured_files"] == []
    assert summary["neighbor_chunks"]["10"]["11"]["captured_files"] == ["c11.npy"]
