import json
from pathlib import Path

import numpy as np

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


def test_replay_loopback_with_report(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello loopback")
    (src / "b.bin").write_bytes(b"\x01\x02\x03" * 1000)

    encoded = build_encoded_frames(
        input_path=str(src),
        block_size=6,
        chunk_size=2048,
        sync_frames=10,
        epochs=2,
    )

    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    for i, item in enumerate(encoded["frames"]):
        np.save(frame_dir / "{0:06d}.npy".format(i), item["image"])

    out_dir = tmp_path / "out"
    report = tmp_path / "report.json"

    code = receiver_main(
        [
            "--source",
            "replay",
            "--frames-dir",
            str(frame_dir),
            "--output-dir",
            str(out_dir),
            "--block-size",
            "6",
            "--report-json",
            str(report),
            "--max-seconds",
            "60",
            "--stats-interval",
            "0.1",
        ]
    )
    assert code == 0
    assert report.exists()

    rep = json.loads(report.read_text(encoding="utf-8"))
    assert rep["status"] == "ok"
    assert rep["goodput_kbps"] >= 0
    assert rep["end_to_end_kbps"] >= 0
    assert 0 <= rep["bad_frame_rate"] <= 1

    restored = out_dir / src.name
    assert restored.exists()
    assert _dir_hash(src) == _dir_hash(restored)
