"""Chunk assembly logic for broadcast receive mode."""

from __future__ import annotations

from typing import Dict, Optional

from screen_airdrop.common.manifest import Manifest


class ChunkAssembler(object):
    def __init__(self):
        self.chunks: Dict[int, bytes] = {}
        self.manifest: Optional[Manifest] = None
        self._received_count: int = 0  # data chunks received (chunk_id > 0), O(1) tracking

    def add(self, chunk_id: int, payload: bytes) -> None:
        if chunk_id not in self.chunks:
            self.chunks[chunk_id] = payload
            if chunk_id == 0:
                if self.manifest is None:
                    self.manifest = Manifest.from_json_bytes(payload)
            else:
                self._received_count += 1

    def complete(self) -> bool:
        if self.manifest is None:
            return False
        return self._received_count >= self.manifest.total_chunks

    def missing_count(self) -> Optional[int]:
        if self.manifest is None:
            return None
        return max(0, self.manifest.total_chunks - self._received_count)

    def payload(self) -> bytes:
        if self.manifest is None:
            raise RuntimeError("manifest not received")
        parts = []
        for cid in range(1, self.manifest.total_chunks + 1):
            if cid not in self.chunks:
                raise RuntimeError("missing chunk {0}".format(cid))
            parts.append(self.chunks[cid])
        return b"".join(parts)
