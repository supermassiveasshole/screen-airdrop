from __future__ import annotations

import json
from pathlib import Path
from typing import Tuple

from screen_airdrop.receiver.cli import main as receiver_main
from screen_airdrop.sender.controller import build_encoded_frames


def dump_and_replay(
    tmp_path: Path,
    *,
    src: Path,
    protocol: str,
    module_grid: str,
    replay_geometry_mode: str = "stateful",
) -> Tuple[dict, Path]:
    frame_dir = tmp_path / f"{protocol}-frames"
    out_dir = tmp_path / f"{protocol}-out"
    replay_report = tmp_path / f"{protocol}-replay-report.json"
    frame_dir.mkdir()
    encoded = build_encoded_frames(
        input_path=str(src),
        protocol=protocol,
        compress="none",
        sync_frames=4 if protocol == "layered" else 8,
        chunk_fill_ratio=1.0,
        module_grid=module_grid,
        ecc_level="L" if protocol in ("gray4", "layered") else "Q",
        guard_band_modules=1 if protocol in ("compact", "gray4", "layered") else 2,
        corner_size_modules=7 if protocol in ("compact", "gray4", "layered") else 9,
        epochs=1,
    )
    for idx, item in enumerate(encoded):
        import numpy as np

        np.save(frame_dir / f"{idx:06d}.npy", item["image"])

    receiver_code = receiver_main(
        [
            "--source",
            "replay",
            "--frames-dir",
            str(frame_dir),
            "--output-dir",
            str(out_dir),
            "--protocol",
            protocol,
            "--module-grid",
            module_grid,
            "--report-json",
            str(replay_report),
            "--replay-geometry-mode",
            replay_geometry_mode,
            "--max-seconds",
            "120",
            "--stats-interval",
            "0.1",
        ]
    )
    assert receiver_code == 0
    return json.loads(replay_report.read_text(encoding="utf-8")), out_dir
