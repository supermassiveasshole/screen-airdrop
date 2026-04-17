"""Sender report construction helpers."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from screen_airdrop.common.control_plane import (
    CONTROL_FAMILY_GENERATION,
    CONTROL_KIND_LAYOUT,
    CONTROL_KIND_SESSION,
)


def build_sender_report(
    *,
    session_id: int,
    protocol: str,
    layered_profiles: Dict[str, Any],
    sent_frames: int,
    sent_data_frames: int,
    elapsed: float,
    effective_chunk_size: int,
    payload_chunk_count: int,
    payload_frame_count: int,
    data_realizations: int,
    theoretical_payload_kibps: float,
    observed_payload_kibps: float,
    stopped_by_user: bool,
    dump_only: bool,
    control_plane_meta: List[Dict[str, Any]],
    control_summary: str,
    emit_coded_units: bool = False,
    coded_redundancy_count: int = 0,
    coded_degree: int = 0,
    coded_scheme: str = "",
    coded_units_emitted: int = 0,
    coded_generations_skipped: int = 0,
    systematic_generations: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    sender_generation = next(
        (
            item
            for item in control_plane_meta
            if item.get("family") == CONTROL_FAMILY_GENERATION
        ),
        None,
    )
    sender_layout = next(
        (item for item in control_plane_meta if item.get("kind") == CONTROL_KIND_LAYOUT),
        None,
    )
    sender_session = next(
        (item for item in control_plane_meta if item.get("kind") == CONTROL_KIND_SESSION),
        None,
    )
    return {
        "session_id": session_id,
        "protocol": protocol,
        "wire_version": str(sender_layout.get("protocol_version", "")) if isinstance(sender_layout, dict) else "",
        "protocol_profile": {"protocol": protocol, **layered_profiles},
        "sent_frames": sent_frames,
        "sent_data_frames": sent_data_frames,
        "elapsed_s": elapsed,
        "bytes_per_frame": effective_chunk_size,
        "payload_chunk_count": payload_chunk_count,
        "payload_frame_count": payload_frame_count,
        "data_realizations": data_realizations,
        "theoretical_payload_kibps": theoretical_payload_kibps,
        "observed_payload_kibps": observed_payload_kibps,
        "theoretical_goodput_kbps": theoretical_payload_kibps,
        "observed_kbps": observed_payload_kibps,
        "stopped_by_user": stopped_by_user,
        "dump_only": dump_only,
        "control_plane": control_plane_meta,
        "control_plane_kinds": sorted(
            str(item.get("kind", "unknown")) for item in control_plane_meta
        ),
        "control_schema": control_summary,
        "control_session": sender_session,
        "control_layout": sender_layout,
        "control_generation": sender_generation,
        "emit_coded_units": bool(emit_coded_units),
        "coded_redundancy_count": int(coded_redundancy_count),
        "coded_degree": int(coded_degree),
        "coded_scheme": str(coded_scheme or ""),
        "coded_units_emitted": int(coded_units_emitted),
        "coded_generations_skipped": int(coded_generations_skipped),
        "systematic_generations": list(systematic_generations or []),
        **layered_profiles,
    }


def write_sender_report(report_json: Optional[str], report: Dict[str, Any]) -> None:
    if not report_json:
        return
    with open(report_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
