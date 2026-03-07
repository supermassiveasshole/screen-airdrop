import json
from pathlib import Path

import numpy as np
import pytest

from screen_airdrop.receiver.cli import main as receiver_main
from screen_airdrop.sender.controller import build_encoded_frames


def _dir_hash(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    for p in sorted(path.rglob("*")):
        rel = p.relative_to(path).as_posix().encode("utf-8")
        h.update(rel)
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


@pytest.mark.real_data
@pytest.mark.parametrize("dataset", ["docs_small", "bin_small", "mixed_tree"])
@pytest.mark.parametrize("block_size", [4, 6, 8])
def test_real_data_replay(dataset: str, block_size: int, tmp_path: Path):
    fixture_root = Path(__file__).resolve().parents[1] / "fixtures" / "real_data"
    src = fixture_root / dataset

    encoded_gen = build_encoded_frames(
        input_path=str(src),
        block_size=block_size,
        chunk_size=1024 if block_size == 8 else 2048,
        sync_frames=8,
        epochs=2,
    )
    encoded = list(encoded_gen)

    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    for i, item in enumerate(encoded):
        np.save(frame_dir / "{0:06d}.npy".format(i), item["image"])

    out_dir = tmp_path / "out"
    report_path = tmp_path / "report.json"
    code = receiver_main(
        [
            "--source",
            "replay",
            "--frames-dir",
            str(frame_dir),
            "--output-dir",
            str(out_dir),
            "--block-size",
            str(block_size),
            "--report-json",
            str(report_path),
            "--max-seconds",
            "60",
        ]
    )

    assert code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "ok"
    assert "goodput_kbps" in report
    assert "end_to_end_kbps" in report
    assert "bad_frame_rate" in report
    assert "recovery_latency_s" in report

    restored = out_dir / src.name
    assert restored.exists()
    assert _dir_hash(src) == _dir_hash(restored)
