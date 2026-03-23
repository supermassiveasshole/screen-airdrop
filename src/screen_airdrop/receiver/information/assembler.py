# pyright: reportArgumentType=false
"""Chunk assembly logic for broadcast receive mode."""

from __future__ import annotations

import threading
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
from screen_airdrop.common.information import SystematicUnit, TransmissionUnit
from screen_airdrop.common.manifest import Manifest
from screen_airdrop.receiver.information.generation_store import GenerationStore
from screen_airdrop.receiver.information.unit_acceptor import AcceptResult, UnitAcceptor


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
        self._lock = threading.Lock()  # lock for thread-safe updates
        self.generation_store = GenerationStore()
        self.unit_acceptor = UnitAcceptor(self.generation_store)
        self._active_generation_id: int = 0

    def add(self, chunk_id: int, payload: bytes) -> bool:
        """Add a chunk to the assembler.

        Args:
            chunk_id: Chunk ID
            payload: Chunk payload

        Returns:
            True if this is a new chunk, False if it was already received
        """
        with self._lock:
            control_kind = control_kind_from_wire_chunk_id(chunk_id)
            if control_kind is not None:
                is_new = chunk_id not in self.chunks
                if is_new:
                    self.chunks[chunk_id] = payload
                    self._add_control_locked(control_kind, payload)
                return is_new
            unit = SystematicUnit(
                session_id=int(self._default_session_id_locked()),
                generation_id=0,
                generation_size=int(self._default_generation_size_locked()),
                source_index=int(chunk_id),
                payload_size=len(payload),
                payload=payload,
            )
            return self._add_unit_locked(unit)

    def add_control(self, kind: str, payload: bytes) -> None:
        """Add a control frame (thread-safe)."""
        with self._lock:
            self._add_control_locked(kind, payload)

    def _add_control_locked(self, kind: str, payload: bytes) -> None:
        """Add a control frame (caller must hold lock)."""
        if kind not in self.control_items:
            self.control_items[kind] = payload
        if kind == CONTROL_KIND_MANIFEST and self.manifest is None:
            self.manifest = Manifest.from_json_bytes(payload)
            if not self.generations:
                self.generation_store.update_generation_size(0, int(self.manifest.total_chunks))
        elif kind == CONTROL_KIND_GENERATION:
            info = decode_generation_control(payload)
            self.generation_info = info
            generation_id = int(info.get("generation_id", -1))
            if generation_id >= 0:
                self.generations[generation_id] = info
                self._active_generation_id = generation_id
            generation_size = int(info.get("generation_size", 0) or 0)
            if generation_size <= 0:
                generation_size = int(info.get("payload_chunk_count", 0) or 0)
            if generation_id >= 0 and generation_size > 0:
                self.generation_store.update_generation_size(generation_id, generation_size)
        elif kind == CONTROL_KIND_SESSION and self.session_info is None:
            self.session_info = decode_session_bootstrap(payload)
        elif kind == CONTROL_KIND_LAYOUT and self.layout_info is None:
            self.layout_info = decode_layout_bootstrap(payload)

    def _default_session_id_locked(self) -> int:
        if self.session_info is not None and "session_id" in self.session_info:
            return int(self.session_info["session_id"])
        if self.manifest is not None:
            return int(self.manifest.session_id)
        return 0

    def _default_generation_size_locked(self) -> int:
        if self.manifest is not None:
            return int(self.manifest.total_chunks)
        if self.generation_info is not None:
            size = int(self.generation_info.get("generation_size", 0) or 0)
            if size > 0:
                return size
            return int(self.generation_info.get("payload_chunk_count", 0) or 0)
        return 0

    def _active_generation_info_locked(self) -> Optional[Dict[str, object]]:
        return self.generations.get(self._active_generation_id)

    def _resolve_unit_locked(self, unit: TransmissionUnit) -> TransmissionUnit:
        if not isinstance(unit, SystematicUnit):
            return unit

        generation_id = int(unit.generation_id)
        generation_size = int(unit.generation_size)
        source_index = int(unit.source_index)
        if generation_size <= 0:
            info = self._active_generation_info_locked()
            if info is not None:
                generation_id = int(info.get("generation_id", generation_id) or generation_id)
        elif generation_id in self.generations:
            info = self.generations[generation_id]
        else:
            info = self._active_generation_info_locked()
            if info is not None:
                generation_id = int(info.get("generation_id", generation_id) or generation_id)

        if info is not None:
            generation_size = int(info.get("generation_size", 0) or generation_size)
            if generation_size <= 0:
                generation_size = int(info.get("payload_chunk_count", 0) or generation_size)

        return SystematicUnit(
            session_id=int(unit.session_id),
            generation_id=generation_id,
            generation_size=max(0, generation_size),
            source_index=source_index,
            payload_size=len(unit.payload),
            payload=unit.payload,
        )

    def _global_chunk_id_for_unit_locked(self, unit: SystematicUnit) -> int:
        info = self.generations.get(int(unit.generation_id))
        if info is not None:
            source_index_base = int(info.get("source_index_base", 0) or 0)
            if source_index_base > 0:
                return int(source_index_base + int(unit.source_index) - 1)

        manifest_total = int(self.manifest.total_chunks) if self.manifest is not None else 0
        if manifest_total > 0 and len(self.generations) <= 1 and int(unit.generation_id) == 0:
            return int(unit.source_index)
        return int(unit.source_index)

    def _add_unit_locked(self, unit: TransmissionUnit) -> bool:
        resolved_unit = self._resolve_unit_locked(unit)
        size_hint = self._default_generation_size_locked()
        result = self.unit_acceptor.accept(resolved_unit, generation_size_hint=size_hint)
        if result != AcceptResult.ACCEPTED:
            return False
        if isinstance(resolved_unit, SystematicUnit):
            global_chunk_id = self._global_chunk_id_for_unit_locked(resolved_unit)
            if global_chunk_id not in self.chunks:
                self.chunks[global_chunk_id] = resolved_unit.payload
                self._received_count += 1
        return True

    def add_unit(self, unit: TransmissionUnit) -> bool:
        """Add an information-layer unit to the assembler."""
        with self._lock:
            return self._add_unit_locked(unit)

    def complete(self) -> bool:
        with self._lock:
            if self.manifest is None:
                return False
            return self._received_count >= self.manifest.total_chunks

    def missing_count(self) -> Optional[int]:
        with self._lock:
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
