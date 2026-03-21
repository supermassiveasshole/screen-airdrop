import json
from pathlib import Path
from unittest.mock import patch

import numpy as np

from screen_airdrop.receiver.cli import main as receiver_main
from screen_airdrop.sender.controller import build_encoded_frames, run_sender

from ..helpers.dump_replay import dump_and_replay
from ..helpers.protocol_fixture_factory import create_payload_tree
from ..helpers.report_assertions import (
    assert_protocol_debug_structure,
    assert_stable_report_fields,
)


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


def test_sender_can_dump_frames_without_renderer(tmp_path: Path):
    src = tmp_path / "sender-src"
    src.mkdir()
    (src / "payload.txt").write_text("hello dump only")

    frame_dir = tmp_path / "sender-frames"
    report = tmp_path / "sender-report.json"

    code = run_sender(
        input_path=str(src),
        dump_frames=str(frame_dir),
        dump_only=True,
        report_json=str(report),
        fps=12,
        max_epochs=1,
        overlay=False,
        protocol="layered",
        module_grid="224x136",
        chunk_size=2048,
        stats_interval=0.1,
    )

    assert code == 0
    dumped = list(frame_dir.iterdir())
    assert dumped
    rep = json.loads(report.read_text(encoding="utf-8"))
    assert rep["dump_only"] is True
    assert rep["protocol"] == "layered"
    assert rep["sent_frames"] > 0


def test_layered_dump_replay_report_has_protocol_debug(tmp_path: Path):
    src = create_payload_tree(tmp_path, name="layered-src")
    replay_report, out_dir = dump_and_replay(
        tmp_path,
        src=src,
        protocol="layered",
        module_grid="224x136",
    )
    assert_stable_report_fields(replay_report)
    assert_protocol_debug_structure(replay_report, "layered")
    assert replay_report["status"] == "ok"
    assert replay_report["missing_chunks"] == 0
    assert (out_dir / src.name).exists()


def test_layered_dump_replay_240x144_stateful_geometry_completes(tmp_path: Path):
    src = create_payload_tree(tmp_path, name="layered-src-240")
    replay_report, out_dir = dump_and_replay(
        tmp_path,
        src=src,
        protocol="layered",
        module_grid="240x144",
        replay_geometry_mode="stateful",
    )
    assert replay_report["status"] == "ok"
    assert replay_report["missing_chunks"] == 0
    assert replay_report["geometry_state_current"] in {"acquire", "locked"}
    assert "geometry_diagnostics" in replay_report
    assert (out_dir / src.name).exists()


def test_gray4_dump_replay_report_has_protocol_debug(tmp_path: Path):
    src = create_payload_tree(tmp_path, name="gray4-src")
    replay_report, out_dir = dump_and_replay(
        tmp_path,
        src=src,
        protocol="gray4",
        module_grid="100x60",
    )
    assert_stable_report_fields(replay_report)
    assert_protocol_debug_structure(replay_report, "gray4")
    assert replay_report["status"] == "ok"
    assert replay_report["missing_chunks"] == 0
    assert (out_dir / src.name).exists()
