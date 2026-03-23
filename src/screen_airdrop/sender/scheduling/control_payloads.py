"""Sender-side control-plane payload builders."""

from __future__ import annotations

from typing import Any, Optional

from screen_airdrop.common.control_plane import (
    encode_generation_control,
    encode_layout_bootstrap,
    encode_session_bootstrap,
)
from screen_airdrop.common.manifest import Manifest
from screen_airdrop.sender.transport.layered.encoder import (
    layered_body_profile_id_for_ecc_level,
    layered_control_layout_metadata,
    layered_profile_metadata,
)


def build_layout_control_payload(
    *,
    protocol: str,
    layout_info: Any,
    ecc_level: str,
    frame_payload_cap: int,
    effective_chunk_size: int,
    module_grid: str,
) -> bytes:
    """Build transport/layout bootstrap payload."""
    layered_body_profile_id = layered_body_profile_id_for_ecc_level(ecc_level)
    return encode_layout_bootstrap(
        {
            "protocol": protocol,
            "protocol_version": getattr(layout_info, "protocol_version", ""),
            "frame_w": int(getattr(layout_info, "frame_w", 0)),
            "frame_h": int(getattr(layout_info, "frame_h", 0)),
            "grid_w": int(getattr(layout_info, "grid_w", 0)),
            "grid_h": int(getattr(layout_info, "grid_h", 0)),
            "bits_per_module": int(getattr(layout_info, "bits_per_module", 0)),
            "guard_band": int(getattr(layout_info, "guard_band", 0)),
            "quiet_zone": int(getattr(layout_info, "quiet_zone", 0)),
            "finder_size": int(getattr(layout_info, "finder_size", 0)),
            "ecc_level": ecc_level,
            "frame_payload_cap": int(frame_payload_cap),
            "effective_chunk_size": int(effective_chunk_size),
            "module_grid": module_grid,
            **(
                {
                    **layered_profile_metadata(layered_body_profile_id),
                    **layered_control_layout_metadata(
                        int(getattr(layout_info, "grid_w", 0)),
                        int(getattr(layout_info, "grid_h", 0)),
                        int(getattr(layout_info, "guard_band", 0)),
                        int(getattr(layout_info, "finder_size", 0)),
                        layered_body_profile_id,
                    ),
                }
                if protocol == "layered"
                else {}
            ),
        }
    )


def build_session_control_payload(
    *,
    session_id: int,
    manifest: Manifest,
    protocol: str,
    window_name: Optional[str],
) -> bytes:
    """Build session/bootstrap payload."""
    return encode_session_bootstrap(
        {
            "session_id": int(session_id),
            "protocol": protocol,
            "protocol_version": int(manifest.protocol_version),
            "created_at": manifest.created_at,
            "input_root_name": manifest.input_root_name,
            "pack": manifest.pack,
            "compress": manifest.compress,
            "window_name": "" if window_name is None else str(window_name),
        }
    )


def build_generation_control_payload(
    *,
    generation_id: int,
    generation_size: int,
    source_index_base: int,
    total_frames: int,
    payload_chunk_count: int,
    effective_chunk_size: int,
    protocol: str,
) -> bytes:
    """Build generation control payload."""
    return encode_generation_control(
        {
            "generation_id": int(generation_id),
            "generation_size": int(generation_size),
            "source_index_base": int(source_index_base),
            "total_frames": int(total_frames),
            "payload_chunk_count": int(payload_chunk_count),
            "effective_chunk_size": int(effective_chunk_size),
            "protocol": protocol,
        }
    )
