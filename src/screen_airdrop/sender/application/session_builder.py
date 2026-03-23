"""Sender-side payload and manifest preparation helpers."""

from __future__ import annotations

import json
from typing import Any, Dict

from screen_airdrop.common.control_plane import (
    CONTROL_KIND_MANIFEST,
    CONTROL_WIRE_CHUNK_IDS,
    ControlPlaneItem,
)
from screen_airdrop.common.manifest import Manifest
from screen_airdrop.common.packing import build_payload_and_manifest


def build_sender_session(
    input_path: str,
    compress: str,
    chunk_size: int,
    session_id: int,
) -> Dict[str, Any]:
    """Build payload bytes, manifest, and initial manifest control item."""
    payload, manifest, payload_chunks = build_payload_and_manifest(
        input_path=input_path,
        compress_method=compress,
        chunk_size=chunk_size,
        session_id=session_id,
    )
    manifest_bytes = manifest.to_json_bytes()
    if len(manifest_bytes) > int(chunk_size):
        compact = Manifest(
            protocol_version=manifest.protocol_version,
            session_id=manifest.session_id,
            created_at=manifest.created_at,
            input_root_name=manifest.input_root_name,
            pack=manifest.pack,
            compress=manifest.compress,
            chunk_size=manifest.chunk_size,
            total_chunks=manifest.total_chunks,
            payload_size=manifest.payload_size,
            payload_sha256=manifest.payload_sha256,
            entries=[],
        )
        manifest_bytes = compact.to_json_bytes()
    if len(manifest_bytes) > int(chunk_size):
        mini = {
            "v": manifest.protocol_version,
            "sid": manifest.session_id,
            "at": manifest.created_at,
            "root": manifest.input_root_name,
            "pk": manifest.pack,
            "cp": manifest.compress,
            "cs": manifest.chunk_size,
            "tc": manifest.total_chunks,
            "ps": manifest.payload_size,
            "sha": manifest.payload_sha256,
        }
        manifest_bytes = json.dumps(mini, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if len(manifest_bytes) > int(chunk_size):
        raise RuntimeError("manifest chunk too large even in mini format")
    control_items = [
        ControlPlaneItem(
            kind=CONTROL_KIND_MANIFEST,
            payload=manifest_bytes,
            wire_chunk_id=CONTROL_WIRE_CHUNK_IDS[CONTROL_KIND_MANIFEST],
        )
    ]
    return {
        "payload": payload,
        "manifest": manifest,
        "control_items": control_items,
        "payload_chunks": payload_chunks,
    }
