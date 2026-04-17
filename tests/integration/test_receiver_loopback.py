import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from screen_airdrop.common.information import CodingScheme
from screen_airdrop.receiver.cli import main as receiver_main
from screen_airdrop.sender.application.controller import build_encoded_frames, run_sender

from ..helpers.dump_replay import dump_and_replay
from ..helpers.protocol_fixture_factory import create_payload_tree
from ..helpers.report_assertions import (
    assert_erasure_experiment_fields,
    assert_protocol_debug_structure,
    assert_stable_report_fields,
)

pytestmark = pytest.mark.replay


def _dir_hash(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    for p in sorted(path.rglob("*")):
        rel = p.relative_to(path).as_posix().encode("utf-8")
        h.update(rel)
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def _run_replay_from_items(
    tmp_path: Path,
    *,
    src: Path,
    items: list[dict],
    source_mode: str = "replay",
    simulated_live_pacing: str = "none",
    protocol: str = "basic",
    module_grid: str = "160x96",
    max_seconds: int = 0,
    max_idle_seconds: int = 3,
    allowed_exit_codes: tuple[int, ...] = (0,),
) -> tuple[dict, Path]:
    frame_dir = tmp_path / "frames"
    frame_dir.mkdir(parents=True)
    for i, item in enumerate(items):
        np.save(frame_dir / "{0:06d}.npy".format(i), item["image"])

    out_dir = tmp_path / "out"
    report = tmp_path / "report.json"
    code = receiver_main(
        [
            "--source",
            source_mode,
            "--frames-dir",
            str(frame_dir),
            "--output-dir",
            str(out_dir),
            "--protocol",
            protocol,
            "--module-grid",
            module_grid,
            "--report-json",
            str(report),
            "--max-idle-seconds",
            str(max_idle_seconds),
            "--max-seconds",
            str(max_seconds),
            "--stats-interval",
            "0.1",
            "--simulated-live-pacing",
            simulated_live_pacing,
        ]
    )
    assert code in allowed_exit_codes
    return json.loads(report.read_text(encoding="utf-8")), out_dir


def _drop_generation_systematics(
    items: list[dict],
    *,
    generation_id: int,
    chunk_ids: set[int],
) -> list[dict]:
    filtered = []
    dropped = set()
    for item in items:
        if (
            item.get("plane") == "data"
            and not item.get("is_coded")
            and int(item.get("generation_id", -1)) == int(generation_id)
            and int(item.get("chunk_id", -1)) in chunk_ids
        ):
            dropped.add(int(item.get("chunk_id", -1)))
            continue
        filtered.append(item)
    assert dropped == set(int(v) for v in chunk_ids)
    return filtered


def _short_generation_plan(items: list[dict]) -> dict:
    metadata = next(item["metadata"] for item in items if "metadata" in item)
    plans = list(metadata["systematic_generations"])
    generation_size = int(metadata["systematic_generation_size"])
    return next(plan for plan in plans if int(plan["generation_size"]) < generation_size)


def _drop_generation_coded(
    items: list[dict],
    *,
    generation_id: int,
    equation_ids: set[int],
) -> list[dict]:
    filtered = []
    dropped = set()
    for item in items:
        if (
            item.get("plane") == "data"
            and item.get("is_coded")
            and int(item.get("generation_id", -1)) == int(generation_id)
            and int(item.get("equation_id", -1)) in equation_ids
        ):
            dropped.add(int(item.get("equation_id", -1)))
            continue
        filtered.append(item)
    assert dropped == set(int(v) for v in equation_ids)
    return filtered


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


def test_simulated_live_loopback_with_report(tmp_path: Path):
    src = tmp_path / "src-sim-live"
    src.mkdir()
    (src / "a.txt").write_text("hello simulated live")
    (src / "b.bin").write_bytes(b"\x01\x02\x03" * 256)

    encoded = list(
        build_encoded_frames(
            input_path=str(src),
            block_size=6,
            chunk_size=2048,
            sync_frames=6,
            epochs=1,
        )
    )

    rep, out_dir = _run_replay_from_items(
        tmp_path,
        src=src,
        items=encoded,
        source_mode="simulated_live",
        max_seconds=30,
    )

    assert rep["status"] == "ok"
    assert rep["runtime_mode"] == "simulated_live"
    assert rep["producer_mode"] == "frames_dir"
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

    with patch("screen_airdrop.sender.application.controller.CV2Renderer", _FakeRenderer):
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
    assert rep["emit_coded_units"] is False
    assert rep["coded_units_emitted"] == 0
    assert isinstance(rep["systematic_generations"], list)


def test_sender_report_exposes_experimental_coded_surface(tmp_path: Path):
    src = tmp_path / "sender-coded-src"
    src.mkdir()
    (src / "payload.bin").write_bytes(b"x" * 4096)

    frame_dir = tmp_path / "sender-coded-frames"
    report = tmp_path / "sender-coded-report.json"

    code = run_sender(
        input_path=str(src),
        dump_frames=str(frame_dir),
        dump_only=True,
        report_json=str(report),
        fps=12,
        max_epochs=1,
        overlay=False,
        protocol="basic",
        chunk_size=256,
        stats_interval=0.1,
        emit_coded_units=True,
        coded_redundancy_count=2,
        coded_degree=3,
    )

    assert code == 0
    rep = json.loads(report.read_text(encoding="utf-8"))
    assert rep["emit_coded_units"] is True
    assert int(rep["coded_redundancy_count"]) == 2
    assert int(rep["coded_degree"]) == 3
    assert rep["coded_scheme"] == "gf256_seed_v2"
    assert int(rep["coded_units_emitted"]) >= 0
    assert int(rep["coded_generations_skipped"]) == sum(
        1
        for plan in rep["systematic_generations"]
        if str(plan["coded_emission_mode"]).startswith("skipped_")
    )
    assert any(
        str(plan["coded_emission_mode"]) in {"enabled", "skipped_variable_size"}
        for plan in rep["systematic_generations"]
    )
    assert all("coded_degree_effective" in plan for plan in rep["systematic_generations"])


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


def test_replay_loopback_with_multiple_systematic_generations(tmp_path: Path):
    src = tmp_path / "src-multi-gen"
    src.mkdir()
    (src / "payload.bin").write_bytes((b"0123456789abcdef" * 1024))

    encoded = list(
        build_encoded_frames(
            input_path=str(src),
            block_size=6,
            chunk_size=256,
            compress="none",
            systematic_generation_size=3,
            sync_frames=4,
            epochs=1,
        )
    )

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

    rep = json.loads(report.read_text(encoding="utf-8"))
    assert rep["status"] == "ok"
    assert rep["missing_chunks"] == 0
    assert len(rep["control_generations_seen"]) >= 2
    restored = out_dir / src.name
    assert restored.exists()
    assert _dir_hash(src) == _dir_hash(restored)


@pytest.mark.erasure_experiment
def test_replay_loopback_can_recover_missing_systematic_chunk_via_coded_unit(tmp_path: Path):
    src = tmp_path / "src-coded"
    src.mkdir()
    (src / "payload.bin").write_bytes(b"0123456789abcdef" * 1024)

    encoded = list(
        build_encoded_frames(
            input_path=str(src),
            protocol="basic",
            compress="none",
            chunk_size=256,
            systematic_generation_size=3,
            emit_coded_units=True,
            coded_redundancy_count=1,
            coded_degree=3,
            sync_frames=4,
            epochs=1,
        )
    )

    dropped = False
    filtered = []
    for item in encoded:
        if (
            not dropped
            and item.get("plane") == "data"
            and not item.get("is_coded")
            and int(item.get("generation_id", -1)) == 0
            and int(item.get("chunk_id", -1)) == 1
        ):
            dropped = True
            continue
        filtered.append(item)

    assert dropped is True
    assert any(item.get("is_coded") for item in filtered)

    frame_dir = tmp_path / "frames-coded"
    frame_dir.mkdir()
    for i, item in enumerate(filtered):
        np.save(frame_dir / "{0:06d}.npy".format(i), item["image"])

    out_dir = tmp_path / "out-coded"
    report = tmp_path / "report-coded.json"
    code = receiver_main(
        [
            "--source",
            "replay",
            "--frames-dir",
            str(frame_dir),
            "--output-dir",
            str(out_dir),
            "--protocol",
            "basic",
            "--report-json",
            str(report),
            "--max-seconds",
            "60",
            "--stats-interval",
            "0.1",
        ]
    )

    assert code == 0
    rep = json.loads(report.read_text(encoding="utf-8"))
    assert rep["status"] == "ok"
    assert_erasure_experiment_fields(rep)
    assert int(rep["coded_units_seen"]) >= 1
    assert int(rep["recovered_source_symbols"]) >= 3
    restored = out_dir / src.name
    assert restored.exists()
    assert _dir_hash(src) == _dir_hash(restored)


@pytest.mark.erasure_experiment
def test_dump_replay_helper_supports_experimental_coded_parameters(tmp_path: Path):
    src = create_payload_tree(tmp_path, name="coded-helper-src")
    replay_report, out_dir = dump_and_replay(
        tmp_path,
        src=src,
        protocol="basic",
        module_grid="160x96",
        emit_coded_units=True,
        coded_redundancy_count=1,
        coded_degree=3,
    )

    assert replay_report["status"] == "ok"
    assert_erasure_experiment_fields(replay_report)
    assert (out_dir / src.name).exists()


@pytest.mark.erasure_experiment
def test_replay_loopback_can_recover_multiple_missing_chunks_via_coded_units(tmp_path: Path):
    src = tmp_path / "src-coded-multi"
    src.mkdir()
    (src / "payload.bin").write_bytes(b"abcdefgh" * 1024)

    encoded = list(
        build_encoded_frames(
            input_path=str(src),
            protocol="basic",
            compress="none",
            chunk_size=256,
            systematic_generation_size=4,
            emit_coded_units=True,
            coded_redundancy_count=4,
            coded_degree=2,
            sync_frames=4,
            epochs=1,
        )
    )

    filtered = _drop_generation_systematics(encoded, generation_id=0, chunk_ids={2, 4})
    rep, out_dir = _run_replay_from_items(tmp_path, src=src, items=filtered, max_seconds=120)

    assert rep["status"] == "ok"
    assert_erasure_experiment_fields(rep)
    assert int(rep["coded_units_seen"]) >= 4
    restored = out_dir / src.name
    assert restored.exists()
    assert _dir_hash(src) == _dir_hash(restored)


@pytest.mark.erasure_experiment
def test_replay_loopback_duplicate_coded_equation_is_observable(tmp_path: Path):
    src = tmp_path / "src-coded-duplicate"
    src.mkdir()
    (src / "payload.bin").write_bytes(b"0123456789abcdef" * 1024)

    encoded = list(
        build_encoded_frames(
            input_path=str(src),
            protocol="basic",
            compress="none",
            chunk_size=256,
            systematic_generation_size=3,
            emit_coded_units=True,
            coded_redundancy_count=1,
            coded_degree=3,
            sync_frames=4,
            epochs=1,
        )
    )

    filtered = list(encoded)
    duplicate_index = next(i for i, item in enumerate(filtered) if item.get("is_coded"))
    filtered.insert(duplicate_index + 1, dict(filtered[duplicate_index]))
    rep, out_dir = _run_replay_from_items(tmp_path, src=src, items=filtered, max_seconds=120)

    assert rep["status"] == "ok"
    assert_erasure_experiment_fields(rep)
    assert int(rep["coded_units_seen"]) >= 1
    assert int(rep["coded_units_duplicate"]) >= 1
    restored = out_dir / src.name
    assert restored.exists()
    assert _dir_hash(src) == _dir_hash(restored)


@pytest.mark.erasure_experiment
def test_replay_loopback_insufficient_coded_equations_do_not_false_complete(tmp_path: Path):
    src = tmp_path / "src-coded-insufficient"
    src.mkdir()
    (src / "payload.bin").write_bytes(b"ABCDEFGH" * 1024)

    encoded = list(
        build_encoded_frames(
            input_path=str(src),
            protocol="basic",
            compress="none",
            chunk_size=256,
            systematic_generation_size=4,
            emit_coded_units=True,
            coded_redundancy_count=1,
            coded_degree=2,
            sync_frames=4,
            epochs=1,
        )
    )

    filtered = _drop_generation_systematics(encoded, generation_id=0, chunk_ids={2, 4})
    rep, out_dir = _run_replay_from_items(
        tmp_path,
        src=src,
        items=filtered,
        max_seconds=0,
        max_idle_seconds=1,
        allowed_exit_codes=(2,),
    )

    assert rep["status"] == "timeout_idle"
    assert int(rep["missing_chunks"]) > 0
    assert_erasure_experiment_fields(rep)
    restored = out_dir / src.name
    assert not restored.exists()


@pytest.mark.erasure_experiment
def test_replay_loopback_can_recover_missing_short_tail_chunk_via_coded_unit(tmp_path: Path):
    src = tmp_path / "src-coded-short-tail"
    src.mkdir()
    (src / "payload.bin").write_bytes(b"x" * 100)

    encoded = list(
        build_encoded_frames(
            input_path=str(src),
            protocol="basic",
            compress="none",
            chunk_size=256,
            systematic_generation_size=3,
            emit_coded_units=True,
            coded_redundancy_count=1,
            coded_degree=4,
            sync_frames=4,
            epochs=1,
        )
    )

    tail_plan = _short_generation_plan(encoded)
    assert int(tail_plan["generation_size"]) == 1
    assert str(tail_plan["coded_emission_mode"]) == "enabled"
    assert int(tail_plan["coded_degree_effective"]) == 1

    filtered = _drop_generation_systematics(
        encoded,
        generation_id=int(tail_plan["generation_id"]),
        chunk_ids={1},
    )
    rep, out_dir = _run_replay_from_items(tmp_path, src=src, items=filtered, max_seconds=60)

    assert rep["status"] == "ok"
    assert_erasure_experiment_fields(rep)
    assert int(rep["coded_units_seen"]) >= 1
    restored = out_dir / src.name
    assert restored.exists()
    assert _dir_hash(src) == _dir_hash(restored)


@pytest.mark.erasure_experiment
def test_replay_loopback_can_recover_two_missing_short_tail_chunks(tmp_path: Path):
    src = tmp_path / "src-coded-short-tail-multi"
    src.mkdir()
    (src / "payload.bin").write_bytes(b"x" * 100)

    encoded = list(
        build_encoded_frames(
            input_path=str(src),
            protocol="basic",
            compress="none",
            chunk_size=256,
            systematic_generation_size=6,
            emit_coded_units=True,
            coded_redundancy_count=4,
            coded_degree=6,
            sync_frames=4,
            epochs=1,
        )
    )

    tail_plan = _short_generation_plan(encoded)
    assert int(tail_plan["generation_size"]) == 4
    assert str(tail_plan["coded_emission_mode"]) == "enabled"
    assert int(tail_plan["coded_degree_effective"]) == 4

    filtered = _drop_generation_systematics(
        encoded,
        generation_id=int(tail_plan["generation_id"]),
        chunk_ids={1, 2},
    )
    rep, out_dir = _run_replay_from_items(tmp_path, src=src, items=filtered, max_seconds=120)

    assert rep["status"] == "ok"
    assert_erasure_experiment_fields(rep)
    assert int(rep["coded_units_seen"]) >= 4
    restored = out_dir / src.name
    assert restored.exists()
    assert _dir_hash(src) == _dir_hash(restored)


@pytest.mark.erasure_experiment
def test_replay_loopback_short_tail_insufficient_equations_remain_incomplete(tmp_path: Path):
    src = tmp_path / "src-coded-short-tail-insufficient"
    src.mkdir()
    (src / "payload.bin").write_bytes(b"x" * 100)

    encoded = list(
        build_encoded_frames(
            input_path=str(src),
            protocol="basic",
            compress="none",
            chunk_size=256,
            systematic_generation_size=6,
            emit_coded_units=True,
            coded_redundancy_count=1,
            coded_degree=6,
            sync_frames=4,
            epochs=1,
        )
    )

    tail_plan = _short_generation_plan(encoded)
    assert int(tail_plan["generation_size"]) == 4
    assert int(tail_plan["coded_degree_effective"]) == 4

    filtered = _drop_generation_systematics(
        encoded,
        generation_id=int(tail_plan["generation_id"]),
        chunk_ids={1, 2},
    )
    rep, out_dir = _run_replay_from_items(
        tmp_path,
        src=src,
        items=filtered,
        max_seconds=0,
        max_idle_seconds=1,
        allowed_exit_codes=(2,),
    )

    assert rep["status"] == "timeout_idle"
    assert int(rep["missing_chunks"]) > 0
    assert_erasure_experiment_fields(rep)
    restored = out_dir / src.name
    assert not restored.exists()


@pytest.mark.erasure_experiment
def test_replay_loopback_v2_single_loss_recovers_where_v1_does_not(tmp_path: Path):
    src = tmp_path / "src-v1-v2-compare"
    src.mkdir()
    (src / "payload.bin").write_bytes(b"0123456789abcdef" * 1024)

    common_kwargs = {
        "input_path": str(src),
        "protocol": "basic",
        "compress": "none",
        "chunk_size": 256,
        "systematic_generation_size": 6,
        "emit_coded_units": True,
        "coded_redundancy_count": 2,
        "coded_degree": 2,
        "sync_frames": 4,
        "epochs": 1,
    }
    encoded_v1 = list(build_encoded_frames(coded_scheme=CodingScheme.GF256_SEED_V1, **common_kwargs))
    encoded_v2 = list(build_encoded_frames(coded_scheme=CodingScheme.GF256_SEED_V2, **common_kwargs))

    filtered_v1 = _drop_generation_systematics(encoded_v1, generation_id=0, chunk_ids={1})
    filtered_v2 = _drop_generation_systematics(encoded_v2, generation_id=0, chunk_ids={1})

    rep_v1, _out_dir_v1 = _run_replay_from_items(
        tmp_path / "v1",
        src=src,
        items=filtered_v1,
        max_seconds=0,
        max_idle_seconds=1,
        allowed_exit_codes=(2,),
    )
    rep_v2, out_dir_v2 = _run_replay_from_items(
        tmp_path / "v2",
        src=src,
        items=filtered_v2,
        max_seconds=120,
    )

    assert rep_v1["status"] == "timeout_idle"
    assert int(rep_v1["missing_chunks"]) > 0
    assert rep_v2["status"] == "ok"
    restored = out_dir_v2 / src.name
    assert restored.exists()
    assert _dir_hash(src) == _dir_hash(restored)


@pytest.mark.erasure_experiment
def test_replay_loopback_coded_only_loss_is_nonfatal(tmp_path: Path):
    src = tmp_path / "src-coded-only-loss"
    src.mkdir()
    (src / "payload.bin").write_bytes(b"abcdefgh" * 1024)

    encoded = list(
        build_encoded_frames(
            input_path=str(src),
            protocol="basic",
            compress="none",
            chunk_size=256,
            systematic_generation_size=6,
            emit_coded_units=True,
            coded_redundancy_count=2,
            coded_degree=3,
            coded_scheme=CodingScheme.GF256_SEED_V2,
            sync_frames=4,
            epochs=1,
        )
    )

    filtered = _drop_generation_coded(encoded, generation_id=0, equation_ids={0})
    rep, out_dir = _run_replay_from_items(tmp_path, src=src, items=filtered, max_seconds=120)

    assert rep["status"] == "ok"
    restored = out_dir / src.name
    assert restored.exists()
    assert _dir_hash(src) == _dir_hash(restored)


@pytest.mark.erasure_experiment
def test_replay_loopback_mixed_systematic_and_coded_loss_can_still_recover(tmp_path: Path):
    src = tmp_path / "src-mixed-loss"
    src.mkdir()
    (src / "payload.bin").write_bytes(b"abcdefgh" * 1024)

    encoded = list(
        build_encoded_frames(
            input_path=str(src),
            protocol="basic",
            compress="none",
            chunk_size=256,
            systematic_generation_size=6,
            emit_coded_units=True,
            coded_redundancy_count=4,
            coded_degree=3,
            coded_scheme=CodingScheme.GF256_SEED_V2,
            sync_frames=4,
            epochs=1,
        )
    )

    filtered = _drop_generation_systematics(encoded, generation_id=0, chunk_ids={1})
    filtered = _drop_generation_coded(filtered, generation_id=0, equation_ids={0})
    rep, out_dir = _run_replay_from_items(tmp_path, src=src, items=filtered, max_seconds=120)

    assert rep["status"] == "ok"
    assert int(rep["coded_units_seen"]) >= 1
    restored = out_dir / src.name
    assert restored.exists()
    assert _dir_hash(src) == _dir_hash(restored)
