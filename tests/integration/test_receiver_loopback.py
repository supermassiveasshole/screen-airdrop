import json
from pathlib import Path
from unittest.mock import patch

import numpy as np

from screen_airdrop.receiver.cli import main as receiver_main
from screen_airdrop.sender.controller import build_encoded_frames, run_sender


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

    encoded_gen = build_encoded_frames(
        input_path=str(src),
        block_size=6,
        chunk_size=2048,
        sync_frames=10,
        epochs=2,
    )
    encoded = list(encoded_gen)

    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    for i, item in enumerate(encoded):
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
    assert rep["control_plane_kinds"] == ["generation", "layout", "manifest", "session"]
    assert rep["control_session"]["input_root_name"] == src.name
    assert rep["control_layout"]["module_grid"] == "160x96"
    assert rep["control_generation"]["generation_id"] >= 0
    assert rep["control_generations_seen"][0] == 0

    restored = out_dir / src.name
    assert restored.exists()
    assert _dir_hash(src) == _dir_hash(restored)


def test_sender_report_includes_control_plane_schema(tmp_path: Path):
    src = tmp_path / "sender-src"
    src.mkdir()
    (src / "payload.txt").write_text("hello sender report")

    frame_dir = tmp_path / "sender-frames"
    report = tmp_path / "sender-report.json"

    class _FakeCV2:
        @staticmethod
        def imwrite(path, image):
            np.save(path + ".npy", image)
            return True

    class _FakeRenderer:
        def __init__(self, window_name, fps, show_overlay):
            self.cv2 = _FakeCV2()
            self._calls = 0

        def show(self, image, overlay_text, pace):
            self._calls += 1
            if self._calls == 1:
                return "toggle_pause"
            return "quit"

        def set_window_title(self, suffix):
            return None

        def reset_clock(self):
            return None

        def close(self):
            return None

    with patch("screen_airdrop.sender.controller.CV2Renderer", _FakeRenderer):
        code = run_sender(
            input_path=str(src),
            dump_frames=str(frame_dir),
            report_json=str(report),
            fps=12,
            max_epochs=1,
            overlay=False,
            protocol="basic",
            chunk_size=2048,
            stats_interval=0.1,
        )

    assert code == 0
    rep = json.loads(report.read_text(encoding="utf-8"))
    assert rep["control_plane_kinds"] == ["generation", "layout", "manifest", "session"]
    assert rep["control_schema"] == "bootstrap/manifest,bootstrap/session,bootstrap/layout,generation/generation"
    assert rep["control_session"]["kind"] == "session"
    assert rep["control_layout"]["kind"] == "layout"
    assert rep["control_generation"]["kind"] == "generation"
