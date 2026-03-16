import importlib.util
import json
from pathlib import Path


def _load_analyzer():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "bench" / "analyze_debug_snapshots.py"
    spec = importlib.util.spec_from_file_location("analyze_debug_snapshots", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_analyze_debug_dir_summarizes_planes_and_errors(tmp_path):
    analyzer = _load_analyzer()
    debug_dir = tmp_path / "debug"
    debug_dir.mkdir()
    (debug_dir / "summary.json").write_text(
        json.dumps(
            {
                "total_frames": 3,
                "planes": {"control": 1, "data": 1, "unknown": 1},
                "control_kinds": {"layout": 1},
                "protocol_paths": {"gray4": 3},
            }
        ),
        encoding="utf-8",
    )
    (debug_dir / "index_all.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "frame_index": 1,
                        "plane": "control",
                        "control_family": "bootstrap",
                        "control_kind": "layout",
                        "protocol_path_used": "gray4",
                        "decode_error": "",
                        "frame_json": "frame_00001.json",
                    }
                ),
                json.dumps(
                    {
                        "frame_index": 2,
                        "plane": "data",
                        "control_family": "",
                        "control_kind": "",
                        "protocol_path_used": "gray4",
                        "decode_error": "crc_failed",
                        "frame_json": "frame_00002.json",
                    }
                ),
                json.dumps(
                    {
                        "frame_index": 3,
                        "plane": "unknown",
                        "control_family": "",
                        "control_kind": "",
                        "protocol_path_used": "gray4",
                        "decode_error": "locator_failed",
                        "frame_json": "frame_00003.json",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (debug_dir / "frame_00001.json").write_text(
        json.dumps(
            {
                "frame_index": 1,
                "decoded_control_kind": "layout",
                "decoded_control_payload": {"decode_error": "control_payload_parse_failed"},
            }
        ),
        encoding="utf-8",
    )
    (debug_dir / "frame_00002.json").write_text(
        json.dumps({"frame_index": 2, "decoded_plane": "data", "decode_error": "crc_failed"}),
        encoding="utf-8",
    )
    (debug_dir / "frame_00003.json").write_text(
        json.dumps(
            {"frame_index": 3, "decoded_plane": "unknown", "decode_error": "locator_failed"}
        ),
        encoding="utf-8",
    )

    summary = analyzer.analyze_debug_dir(debug_dir)

    assert summary["total_frames"] == 3
    assert summary["failed_frames"] == 2
    assert summary["planes"]["control"] == 1
    assert summary["decode_errors"] == {"crc_failed": 1, "locator_failed": 1}
    assert summary["by_plane"]["data"]["failure_frames"] == 1
    assert summary["by_control_kind"]["layout"]["frames"] == 1
    assert summary["by_protocol_path"]["gray4"]["frames"] == 3
    assert summary["control_payload_parse_failures"] == {"layout": 1}
