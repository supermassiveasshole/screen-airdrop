from __future__ import annotations

from typing import Mapping


def assert_stable_report_fields(report: Mapping[str, object]) -> None:
    for key in (
        "status",
        "missing_chunks",
        "bad_frames",
        "valid_frames",
        "goodput_kibps",
        "time_to_first_valid_frame_s",
        "time_to_first_data_frame_s",
        "time_to_first_new_chunk_s",
        "decoded_new_chunks",
        "decoded_duplicate_chunks",
        "control_plane_kinds",
    ):
        assert key in report


def assert_protocol_debug_structure(report: Mapping[str, object], protocol: str) -> None:
    protocol_debug = report.get("protocol_debug")
    assert isinstance(protocol_debug, dict)
    if protocol == "layered":
        layered_debug = protocol_debug.get("layered_debug")
        assert isinstance(layered_debug, dict)
        assert "control_path_version" in layered_debug
        assert isinstance(layered_debug.get("core_header"), dict)
        assert isinstance(layered_debug.get("body"), dict)
        assert isinstance(layered_debug.get("decode_stage_counts"), dict)
    elif protocol == "gray4":
        gray4_debug = protocol_debug.get("gray4_debug")
        assert isinstance(gray4_debug, dict)
        assert isinstance(gray4_debug.get("failure_counts"), dict)
