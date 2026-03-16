"""Chunk assembly logic for broadcast receive mode."""

from __future__ import annotations

from typing import Dict, Optional

from screen_airdrop.common.control_plane import (
    CONTROL_KIND_GENERATION,
    CONTROL_KIND_LAYOUT,
    CONTROL_KIND_MANIFEST,
    CONTROL_KIND_SESSION,
    control_kind_from_wire_chunk_id,
    decode_generation_control,
    decode_layout_bootstrap,
    decode_session_bootstrap,
)
from screen_airdrop.common.manifest import Manifest


class ChunkAssembler(object):
    def __init__(self):
        self.chunks: Dict[int, bytes] = {}
        self.manifest: Optional[Manifest] = None
        self.control_items: Dict[str, bytes] = {}
        self.generation_info: Optional[Dict[str, object]] = None
        self.generations: Dict[int, Dict[str, object]] = {}
        self.session_info: Optional[Dict[str, object]] = None
        self.layout_info: Optional[Dict[str, object]] = None
        self._received_count: int = 0  # data chunks received (chunk_id > 0), O(1) tracking

    def add(self, chunk_id: int, payload: bytes) -> None:
        if chunk_id not in self.chunks:
            self.chunks[chunk_id] = payload
            control_kind = control_kind_from_wire_chunk_id(chunk_id)
            if control_kind is not None:
                self.add_control(control_kind, payload)
            else:
                self._received_count += 1

    def add_control(self, kind: str, payload: bytes) -> None:
        if kind not in self.control_items:
            self.control_items[kind] = payload
        if kind == CONTROL_KIND_MANIFEST and self.manifest is None:
            self.manifest = Manifest.from_json_bytes(payload)
        elif kind == CONTROL_KIND_GENERATION:
            info = decode_generation_control(payload)
            self.generation_info = info
            generation_id = int(info.get("generation_id", -1))
            if generation_id >= 0:
                self.generations[generation_id] = info
        elif kind == CONTROL_KIND_SESSION and self.session_info is None:
            self.session_info = decode_session_bootstrap(payload)
        elif kind == CONTROL_KIND_LAYOUT and self.layout_info is None:
            self.layout_info = decode_layout_bootstrap(payload)

    def complete(self) -> bool:
        if self.manifest is None:
            return False
        return self._received_count >= self.manifest.total_chunks

    def missing_count(self) -> Optional[int]:
        if self.manifest is None:
            return None
        return max(0, self.manifest.total_chunks - self._received_count)

    def missing_chunk_ids(self, limit: int = 32) -> Optional[list[int]]:
        if self.manifest is None:
            return None
        max_items = max(0, int(limit))
        missing: list[int] = []
        for cid in range(1, self.manifest.total_chunks + 1):
            if cid not in self.chunks:
                missing.append(cid)
                if len(missing) >= max_items:
                    break
        return missing

    def payload(self) -> bytes:
        if self.manifest is None:
            raise RuntimeError("manifest not received")
        parts = []
        for cid in range(1, self.manifest.total_chunks + 1):
            if cid not in self.chunks:
                raise RuntimeError("missing chunk {0}".format(cid))
            parts.append(self.chunks[cid])
        return b"".join(parts)
