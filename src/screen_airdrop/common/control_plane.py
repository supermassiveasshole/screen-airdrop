"""Control-plane item definitions shared across sender and receiver."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Optional

CONTROL_FAMILY_BOOTSTRAP = "bootstrap"
CONTROL_FAMILY_GENERATION = "generation"
CONTROL_KIND_MANIFEST = "manifest"
CONTROL_KIND_SESSION = "session"
CONTROL_KIND_LAYOUT = "layout"
CONTROL_KIND_GENERATION = "generation"
CONTROL_WIRE_CHUNK_IDS: Dict[str, int] = {
    CONTROL_KIND_MANIFEST: 0,
    CONTROL_KIND_GENERATION: 0xFFFFFFFC,
    CONTROL_KIND_SESSION: 0xFFFFFFFD,
    CONTROL_KIND_LAYOUT: 0xFFFFFFFE,
}
WIRE_CHUNK_ID_TO_CONTROL_KIND: Dict[int, str] = {
    wire_chunk_id: kind for kind, wire_chunk_id in CONTROL_WIRE_CHUNK_IDS.items()
}


def control_kind_from_wire_chunk_id(wire_chunk_id: int) -> Optional[str]:
    return WIRE_CHUNK_ID_TO_CONTROL_KIND.get(int(wire_chunk_id))


def control_family_for_kind(kind: str) -> str:
    if kind in (CONTROL_KIND_MANIFEST, CONTROL_KIND_SESSION, CONTROL_KIND_LAYOUT):
        return CONTROL_FAMILY_BOOTSTRAP
    if kind == CONTROL_KIND_GENERATION:
        return CONTROL_FAMILY_GENERATION
    return "control"


def encode_generation_control(generation_payload: Dict[str, object]) -> bytes:
    return json.dumps(generation_payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def decode_generation_control(payload: bytes) -> Dict[str, object]:
    return dict(json.loads(payload.decode("utf-8")))


def encode_session_bootstrap(session_payload: Dict[str, object]) -> bytes:
    return json.dumps(session_payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def decode_session_bootstrap(payload: bytes) -> Dict[str, object]:
    return dict(json.loads(payload.decode("utf-8")))


def encode_layout_bootstrap(layout_payload: Dict[str, object]) -> bytes:
    return json.dumps(layout_payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def decode_layout_bootstrap(payload: bytes) -> Dict[str, object]:
    return dict(json.loads(payload.decode("utf-8")))


@dataclass(frozen=True)
class ControlPlaneItem:
    kind: str
    payload: bytes
    wire_chunk_id: int = 0

    def to_metadata(self) -> Dict[str, object]:
        return {
            "kind": self.kind,
            "family": control_family_for_kind(self.kind),
            "wire_chunk_id": int(self.wire_chunk_id),
            "payload_size": len(self.payload),
        }
