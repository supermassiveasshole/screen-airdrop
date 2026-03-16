import importlib.util
import json
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "bench" / "extract_chunk_windows.py"
    spec = importlib.util.spec_from_file_location("extract_chunk_windows", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_windows_copies_neighbor_files(tmp_path):
    module = _load_module()
    sender_dir = tmp_path / "sender"
    captured_dir = tmp_path / "captured"
    output_dir = tmp_path / "out"
    sender_dir.mkdir()
    captured_dir.mkdir()
    (sender_dir / "s10.png").write_bytes(b"sender10")
    (sender_dir / "s11.png").write_bytes(b"sender11")
    (captured_dir / "c11.npy").write_bytes(b"captured11")

    compare_summary = {
        "missing_chunks_requested": [10],
        "neighbor_chunks": {
            "10": {
                "10": {
                    "sender_files": ["s10.png"],
                    "captured_files": [],
                    "sender_frame_ids": [41],
                    "captured_frame_ids": [],
                },
                "11": {
                    "sender_files": ["s11.png"],
                    "captured_files": ["c11.npy"],
                    "sender_frame_ids": [42],
                    "captured_frame_ids": [277],
                },
            }
        },
    }

    extracted = module.extract_windows(compare_summary, sender_dir, captured_dir, output_dir)

    assert (output_dir / "chunk_10" / "sender" / "chunk_10" / "s10.png").exists()
    assert (output_dir / "chunk_10" / "sender" / "chunk_11" / "s11.png").exists()
    assert (output_dir / "chunk_10" / "captured" / "chunk_11" / "c11.npy").exists()
    assert extracted["chunks"]["10"]["neighbors"]["11"]["captured_files"] == ["c11.npy"]
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["chunks"]["10"]["neighbors"]["10"]["sender_frame_ids"] == [41]
