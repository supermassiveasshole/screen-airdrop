"""Manifest schema and serialization helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class Manifest:
    protocol_version: int
    session_id: int
    created_at: str
    input_root_name: str
    pack: str
    compress: str
    chunk_size: int
    total_chunks: int
    payload_size: int
    payload_sha256: str
    entries: List[Dict[str, object]]

    def to_dict(self) -> Dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "input_root_name": self.input_root_name,
            "pack": self.pack,
            "compress": self.compress,
            "chunk_size": self.chunk_size,
            "total_chunks": self.total_chunks,
            "payload_size": self.payload_size,
            "payload_sha256": self.payload_sha256,
            "entries": self.entries,
        }

    def to_json_bytes(self) -> bytes:
        return json.dumps(self.to_dict(), ensure_ascii=True, separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_json_bytes(cls, data: bytes) -> "Manifest":
        payload = json.loads(data.decode("utf-8"))
        if "v" in payload and "sha" in payload:
            # Compact wire format used when frame payload is too small for full schema.
            payload = {
                "protocol_version": int(payload.get("v", 3)),
                "session_id": int(payload.get("sid", 0)),
                "created_at": str(payload.get("at", "")),
                "input_root_name": str(payload.get("root", "payload")),
                "pack": str(payload.get("pk", "tar")),
                "compress": str(payload.get("cp", "gzip")),
                "chunk_size": int(payload.get("cs", 0)),
                "total_chunks": int(payload.get("tc", 0)),
                "payload_size": int(payload.get("ps", 0)),
                "payload_sha256": str(payload.get("sha", "")),
                "entries": [],
            }
        return cls(**payload)
