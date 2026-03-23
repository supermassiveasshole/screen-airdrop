import json
import random
from pathlib import Path

import numpy as np

from screen_airdrop.receiver.cli import main as receiver_main
from screen_airdrop.sender.application.controller import build_encoded_frames


def test_replay_lossy_still_recovers(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "payload.txt").write_text("x" * 20000)

    encoded_gen = build_encoded_frames(
        input_path=str(src),
        block_size=6,
        chunk_size=1024,
        sync_frames=5,
        epochs=4,
    )
    encoded = list(encoded_gen)

    frames = [item for item in encoded if item["kind"] == "data"]
    random.seed(7)
    kept = []
    for f in frames:
        if random.random() < 0.15:
            continue
        kept.append(f)
        if random.random() < 0.05:
            kept.append(f)
    random.shuffle(kept)

    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    for i, item in enumerate(kept):
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
        ]
    )

    assert code == 0
    rep = json.loads(report.read_text(encoding="utf-8"))
    assert rep["status"] == "ok"
    assert rep["goodput_kbps"] >= 0
