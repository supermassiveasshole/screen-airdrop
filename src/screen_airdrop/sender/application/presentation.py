"""Sender presentation helpers for frame labels and overlay text."""

from __future__ import annotations

from typing import Any, Dict


def frame_name_for_item(item: Dict[str, Any]) -> str:
    if item["kind"] == "sync":
        return "sync_{0:06d}.png".format(int(item["frame_id"]))
    if item["kind"] == "data":
        if item.get("plane") == "control":
            return "epoch_{0:06d}_{1}_{2}_{3:06d}.png".format(
                int(item["epoch"]),
                str(item.get("control_family") or "control"),
                str(item.get("control_kind") or "control"),
                int(item["frame_id"]),
            )
        suffix = ""
        realization_count = int(item.get("realization_count", 1) or 1)
        if realization_count > 1:
            suffix = "_r{0:02d}of{1:02d}".format(
                int(item.get("realization_index", 0)) + 1,
                realization_count,
            )
        return "epoch_{0:06d}_frame_{1:06d}{2}.png".format(
            int(item["epoch"]),
            int(item["frame_id"]),
            suffix,
        )
    return "epoch_{0:06d}_end.png".format(int(item["epoch"]))


def overlay_text_for_item(
    item: Dict[str, Any],
    *,
    paused: bool,
    session_id: int,
    sync_frames: int,
    total_data_frames: int,
    effective_chunk_size: int,
    control_burst_repeat: int,
    control_summary: str,
    data_realizations: int,
) -> str:
    if item["kind"] == "sync":
        base = "SYNC {0}/{1}".format(int(item["frame_id"]) + 1, sync_frames)
    elif item["kind"] == "end":
        base = "END epoch={0}".format(int(item["epoch"]))
    else:
        base = "session={0} epoch={1} frame={2}/{3} bytes_per_frame={4}".format(
            session_id,
            int(item["epoch"]),
            int(item["frame_id"]) + 1,
            total_data_frames,
            effective_chunk_size,
        )
        if item.get("plane") == "control":
            base += " control={0}/{1} control_burst={2}".format(
                str(item.get("control_family") or "control"),
                str(item.get("control_kind") or "control"),
                control_burst_repeat,
            )
        elif control_summary:
            base += " control_schema={0}".format(control_summary)
        if item.get("plane") == "data" and data_realizations > 1:
            base += " realization={0}/{1}".format(
                int(item.get("realization_index", 0)) + 1,
                int(item.get("realization_count", data_realizations)),
            )
    if paused:
        return base + " | SPACE start/pause | R reset | Q quit"
    return base + " | SPACE pause | R reset | Q quit"


def window_title_for_state(paused: bool) -> str:
    if paused:
        return "SPACE start | R reset | Q quit"
    return "SPACE pause | R reset | Q quit"
