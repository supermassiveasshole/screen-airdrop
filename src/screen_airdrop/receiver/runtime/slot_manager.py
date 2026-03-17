"""Slot manager: shared memory slot lifecycle and allocation."""

from __future__ import annotations

import threading
from collections import deque
from enum import Enum
from typing import Dict, List, Optional, Tuple


class SlotState(Enum):
    """Slot lifecycle states."""

    FREE = "free"
    FILLING = "filling"
    FILLED = "filled"
    IN_DECODE = "in_decode"
    RECLAIMING = "reclaiming"


class _SlotRecord:
    """Internal slot state record."""

    __slots__ = (
        "slot_id",
        "shm_name",
        "generation",
        "state",
        "writer_owner",
        "decode_owner",
        "dump_reader_ref",
        "current_descriptor",
    )

    def __init__(self, slot_id: int, shm_name: str):
        self.slot_id = slot_id
        self.shm_name = shm_name
        self.generation = 0
        self.state = SlotState.FREE
        self.writer_owner: Optional[str] = None
        self.decode_owner: Optional[str] = None
        self.dump_reader_ref = 0
        self.current_descriptor: Optional[object] = None


class SlotManager:
    """Thread-safe slot lifecycle manager with generation-based versioning.

    Returns (slot_id, generation, shm_name) tuples for compatibility with existing code.
    """

    def __init__(self, shm_names: List[str], *, slot_id_base: int = 0):
        """Initialize slot manager.

        Args:
            shm_names: List of shared memory names
            slot_id_base: Base slot ID (default 0)
        """
        self._slot_id_base = int(slot_id_base)
        self._slots: List[_SlotRecord] = [
            _SlotRecord(slot_id=self._slot_id_base + i, shm_name=name) for i, name in enumerate(shm_names)
        ]
        self._slot_index_by_id: Dict[int, int] = {slot.slot_id: i for i, slot in enumerate(self._slots)}
        self._free_slots: deque[int] = deque(slot.slot_id for slot in self._slots)
        self._lock = threading.Lock()

        # Metrics
        self.slot_in_use_peak = 0
        self.generation_mismatch_count = 0
        self.overwrite_count = 0
        self.overwrite_before_prep_count = 0

    def slot_count(self) -> int:
        """Get total number of slots."""
        return len(self._slots)

    def _slot_for_id_locked(self, slot_id: int) -> Optional[_SlotRecord]:
        """Get slot record by ID (must hold lock)."""
        idx = self._slot_index_by_id.get(slot_id)
        if idx is None:
            return None
        return self._slots[idx]

    def allocate_for_grab(self, writer_owner: str) -> Optional[Tuple[int, int, str]]:
        """Allocate a free slot for grab worker.

        Args:
            writer_owner: Owner identifier (e.g., "grab")

        Returns:
            (slot_id, generation, shm_name) if successful, None if no free slots
        """
        with self._lock:
            if not self._free_slots:
                return None

            slot_id = self._free_slots.popleft()
            slot = self._slot_for_id_locked(slot_id)
            if slot is None:
                return None

            slot.generation += 1
            slot.state = SlotState.FILLING
            slot.writer_owner = writer_owner
            slot.decode_owner = None
            slot.dump_reader_ref = 0
            slot.current_descriptor = None

            self.slot_in_use_peak = max(self.slot_in_use_peak, len(self._slots) - len(self._free_slots))

            return (slot_id, slot.generation, slot.shm_name)

    def overwrite_oldest_filled(self, writer_owner: str) -> Optional[Tuple[int, int, str]]:
        """Reclaim oldest filled slot and allocate for grab worker.

        Args:
            writer_owner: Owner identifier

        Returns:
            (slot_id, generation, shm_name) if successful, None if no filled slots
        """
        with self._lock:
            candidates = [
                slot
                for slot in self._slots
                if slot.state == SlotState.FILLED and slot.current_descriptor is not None
            ]
            if not candidates:
                return None

            # Find oldest by capture_index (assuming current_descriptor has it)
            oldest = min(
                candidates,
                key=lambda s: getattr(s.current_descriptor, "capture_index", 0),
            )

            self._force_reclaim_locked(oldest.slot_id)

            if not self._free_slots:
                return None

            slot_id = self._free_slots.popleft()
            slot = self._slot_for_id_locked(slot_id)
            if slot is None:
                return None

            slot.generation += 1
            slot.state = SlotState.FILLING
            slot.writer_owner = writer_owner
            slot.decode_owner = None
            slot.dump_reader_ref = 0
            slot.current_descriptor = None

            self.slot_in_use_peak = max(self.slot_in_use_peak, len(self._slots) - len(self._free_slots))
            self.overwrite_count += 1
            self.overwrite_before_prep_count += 1

            return (slot_id, slot.generation, slot.shm_name)

    def mark_filled(self, descriptor: object, writer_owner: str) -> bool:
        """Mark slot as filled after grab completes.

        Args:
            descriptor: Frame descriptor with slot_id and generation
            writer_owner: Owner identifier

        Returns:
            True if successful, False if generation mismatch or invalid state
        """
        slot_id = getattr(descriptor, "slot_id", None)
        generation = getattr(descriptor, "generation", None)

        if slot_id is None or generation is None:
            return False

        with self._lock:
            slot = self._slot_for_id_locked(slot_id)
            if slot is None:
                return False

            if slot.writer_owner != writer_owner or slot.state != SlotState.FILLING:
                return False

            if slot.generation != generation:
                self.generation_mismatch_count += 1
                return False

            slot.state = SlotState.FILLED
            slot.writer_owner = None
            slot.current_descriptor = descriptor

            return True

    def descriptor_matches_current(self, descriptor: object) -> bool:
        """Check if descriptor matches current slot state.

        Args:
            descriptor: Frame descriptor with slot_id and generation

        Returns:
            True if descriptor is current, False otherwise
        """
        slot_id = getattr(descriptor, "slot_id", None)
        generation = getattr(descriptor, "generation", None)

        if slot_id is None or generation is None:
            return False

        with self._lock:
            slot = self._slot_for_id_locked(slot_id)
            if slot is None:
                return False

            if slot.generation != generation:
                self.generation_mismatch_count += 1
                return False

            current = slot.current_descriptor
            return current is not None and getattr(current, "generation", None) == generation

    def mark_duplicate_and_release(self, descriptor: object) -> bool:
        """Mark slot as duplicate and release it.

        Args:
            descriptor: Frame descriptor with slot_id and generation

        Returns:
            True if successful, False if generation mismatch
        """
        slot_id = getattr(descriptor, "slot_id", None)
        generation = getattr(descriptor, "generation", None)

        if slot_id is None or generation is None:
            return False

        with self._lock:
            return self._release_locked(slot_id, generation)

    def assign_decode(self, descriptor: object, worker_id: int) -> bool:
        """Assign slot to decode worker.

        Args:
            descriptor: Frame descriptor with slot_id and generation
            worker_id: Decode worker ID

        Returns:
            True if successful, False if generation mismatch or invalid state
        """
        slot_id = getattr(descriptor, "slot_id", None)
        generation = getattr(descriptor, "generation", None)

        if slot_id is None or generation is None:
            return False

        with self._lock:
            slot = self._slot_for_id_locked(slot_id)
            if slot is None:
                return False

            if slot.generation != generation:
                self.generation_mismatch_count += 1
                return False

            if slot.state != SlotState.FILLED:
                return False

            slot.state = SlotState.IN_DECODE
            slot.decode_owner = f"decode:{worker_id}"

            return True

    def set_dump_reader(self, descriptor: object) -> bool:
        """Set dump reader reference on slot.

        Args:
            descriptor: Frame descriptor with slot_id and generation

        Returns:
            True if successful, False if generation mismatch or already set
        """
        slot_id = getattr(descriptor, "slot_id", None)
        generation = getattr(descriptor, "generation", None)

        if slot_id is None or generation is None:
            return False

        with self._lock:
            slot = self._slot_for_id_locked(slot_id)
            if slot is None:
                return False

            if slot.generation != generation:
                self.generation_mismatch_count += 1
                return False

            if slot.dump_reader_ref:
                return False

            slot.dump_reader_ref = 1
            return True

    def clear_dump_reader(self, descriptor: object) -> bool:
        """Clear dump reader reference and release if decode complete.

        Args:
            descriptor: Frame descriptor with slot_id and generation

        Returns:
            True if successful, False if generation mismatch
        """
        slot_id = getattr(descriptor, "slot_id", None)
        generation = getattr(descriptor, "generation", None)

        if slot_id is None or generation is None:
            return False

        with self._lock:
            slot = self._slot_for_id_locked(slot_id)
            if slot is None:
                return False

            if slot.generation != generation:
                self.generation_mismatch_count += 1
                return False

            slot.dump_reader_ref = 0

            if slot.decode_owner is None:
                self._release_locked(slot_id, generation)

            return True

    def complete_decode(self, descriptor: object, worker_id: int) -> bool:
        """Complete decode and release slot if no dump reader.

        Args:
            descriptor: Frame descriptor with slot_id and generation
            worker_id: Decode worker ID

        Returns:
            True if successful, False if generation mismatch or wrong owner
        """
        slot_id = getattr(descriptor, "slot_id", None)
        generation = getattr(descriptor, "generation", None)

        if slot_id is None or generation is None:
            return False

        with self._lock:
            slot = self._slot_for_id_locked(slot_id)
            if slot is None:
                return False

            if slot.generation != generation:
                self.generation_mismatch_count += 1
                return False

            if slot.decode_owner != f"decode:{worker_id}":
                return False

            slot.decode_owner = None

            if slot.dump_reader_ref == 0:
                self._release_locked(slot_id, generation)

            return True

    def reclaim_writer_owner(self, writer_owner: str) -> None:
        """Reclaim all slots owned by writer.

        Args:
            writer_owner: Owner identifier
        """
        with self._lock:
            for slot in self._slots:
                if slot.writer_owner == writer_owner:
                    self._force_reclaim_locked(slot.slot_id)

    def reclaim_decode_owner(self, worker_id: int) -> None:
        """Reclaim all slots owned by decode worker.

        Args:
            worker_id: Decode worker ID
        """
        target = f"decode:{worker_id}"
        with self._lock:
            for slot in self._slots:
                if slot.decode_owner == target:
                    self._force_reclaim_locked(slot.slot_id)

    def reclaim_dump_reader(self) -> None:
        """Reclaim all slots with dump reader reference."""
        with self._lock:
            for slot in self._slots:
                if slot.dump_reader_ref:
                    slot.dump_reader_ref = 0
                    if slot.decode_owner is None and slot.state != SlotState.FILLING:
                        self._release_locked(slot.slot_id, slot.generation)

    def snapshot_slot_in_use_peak(self) -> int:
        """Get peak slot usage."""
        with self._lock:
            return self.slot_in_use_peak

    def snapshot_generation_mismatch(self) -> int:
        """Get generation mismatch count."""
        with self._lock:
            return self.generation_mismatch_count

    def snapshot_overwrite_count(self) -> int:
        """Get overwrite count."""
        with self._lock:
            return self.overwrite_count

    def snapshot_overwrite_before_prep_count(self) -> int:
        """Get overwrite before prep count."""
        with self._lock:
            return self.overwrite_before_prep_count

    def _force_reclaim_locked(self, slot_id: int) -> None:
        """Force reclaim slot (must hold lock)."""
        slot = self._slot_for_id_locked(slot_id)
        if slot is None:
            return

        slot.state = SlotState.RECLAIMING
        slot.generation += 1
        slot.writer_owner = None
        slot.decode_owner = None
        slot.dump_reader_ref = 0
        slot.current_descriptor = None
        slot.state = SlotState.FREE

        if slot_id not in self._free_slots:
            self._free_slots.append(slot_id)

    def _release_locked(self, slot_id: int, generation: int) -> bool:
        """Release slot (must hold lock)."""
        slot = self._slot_for_id_locked(slot_id)
        if slot is None:
            return False

        if slot.generation != generation:
            self.generation_mismatch_count += 1
            return False

        slot.state = SlotState.FREE
        slot.writer_owner = None
        slot.decode_owner = None
        slot.dump_reader_ref = 0
        slot.current_descriptor = None

        if slot_id not in self._free_slots:
            self._free_slots.append(slot_id)

        return True
