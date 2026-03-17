"""Prep strategies: async vs process-based fingerprinting."""

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, Optional, Sequence, Tuple

import numpy as np

from screen_airdrop.receiver.runtime.events import (
    DuplicateSlotEvent,
    FilledSlotEvent,
    PreparedSlotEvent,
)
from screen_airdrop.receiver.runtime.frame_preprocessor import compute_fingerprint, fingerprint_diff


class PrepStrategy(ABC):
    """Abstract prep strategy."""

    @abstractmethod
    async def start(self, coord_queue: asyncio.Queue) -> None:
        """Start prep processing.

        Args:
            coord_queue: Queue to send prep results to coordinator
        """
        pass

    @abstractmethod
    async def submit(self, event: Any) -> None:
        """Submit a filled slot event for prep processing.

        Args:
            event: FilledSlotEvent from grab worker
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop prep processing."""
        pass


class AsyncPrepStrategy(PrepStrategy):
    """Async prep: fingerprinting in coordinator's event loop."""

    def __init__(
        self,
        slot_views: Sequence[np.ndarray],
        prep_roi: Tuple[int, int, int, int],
    ) -> None:
        """Initialize async prep strategy.

        Args:
            slot_views: List of numpy arrays for each slot
            prep_roi: (x, y, w, h) region of interest for fingerprinting
        """
        self._slot_views = slot_views
        self._prep_roi = prep_roi
        self._input_queue: Optional[asyncio.Queue] = None
        self._coord_queue: Optional[asyncio.Queue] = None
        self._task: Optional[asyncio.Task] = None
        self._last_fingerprint: Optional[bytes] = None

    async def start(self, coord_queue: asyncio.Queue) -> None:
        """Start async prep loop."""
        self._input_queue = asyncio.Queue()
        self._coord_queue = coord_queue
        self._task = asyncio.create_task(self._prep_loop())

    async def submit(self, event: Any) -> None:
        """Submit event to async prep queue."""
        assert self._input_queue is not None
        await self._input_queue.put(event)

    async def stop(self) -> None:
        """Stop async prep loop."""
        if self._input_queue is not None:
            await self._input_queue.put(None)
        if self._task is not None:
            await self._task

    async def _prep_loop(self) -> None:
        """Async prep loop for fingerprinting."""
        assert self._input_queue is not None
        assert self._coord_queue is not None

        while True:
            event = await self._input_queue.get()
            if event is None:
                break

            if not isinstance(event, FilledSlotEvent):
                continue

            descriptor = event.descriptor

            try:
                # Extract ROI from frame
                x, y, w, h = self._prep_roi
                frame_roi = self._slot_views[descriptor.slot_id][y : y + h, x : x + w]

                # Compute fingerprint
                t0 = time.perf_counter()
                fingerprint = await asyncio.to_thread(compute_fingerprint, frame_roi)
                t1 = time.perf_counter()
                fingerprint_ms = (t1 - t0) * 1000.0

                # Check for duplicate
                t2 = time.perf_counter()
                dedup_score = fingerprint_diff(fingerprint, self._last_fingerprint)
                t3 = time.perf_counter()
                dedup_decision_ms = (t3 - t2) * 1000.0

                if dedup_score < 0.015:  # Duplicate threshold
                    # Duplicate frame
                    dup_event = DuplicateSlotEvent(
                        descriptor=descriptor,
                        fingerprint=fingerprint,
                        fingerprint_ms=fingerprint_ms,
                        dedup_score=dedup_score,
                        dedup_decision_ms=dedup_decision_ms,
                    )
                    await self._coord_queue.put(("prep", dup_event))
                else:
                    # New frame
                    self._last_fingerprint = fingerprint
                    prep_event = PreparedSlotEvent(
                        descriptor=descriptor,
                        fingerprint=fingerprint,
                        fingerprint_ms=fingerprint_ms,
                        dedup_score=dedup_score,
                        dedup_decision_ms=dedup_decision_ms,
                    )
                    await self._coord_queue.put(("prep", prep_event))
            except Exception as exc:
                # Single frame error - send a skip event so coordinator can recycle the slot
                await self._coord_queue.put(("prep", {
                    "kind": "prep_skip",
                    "descriptor": descriptor,
                    "error": str(exc),
                }))


class ProcessPrepStrategy(PrepStrategy):
    """Process prep: fingerprinting in separate process."""

    def __init__(self, prep_input_queue: Any, prep_output_queue: Any) -> None:
        """Initialize process prep strategy.

        Args:
            prep_input_queue: Multiprocessing queue for prep input
            prep_output_queue: Multiprocessing queue for prep results
        """
        self._prep_input_queue = prep_input_queue
        self._prep_output_queue = prep_output_queue

    async def start(self, coord_queue: asyncio.Queue) -> None:
        """Start prep strategy (no-op for process mode)."""
        pass

    async def submit(self, event: Any) -> None:
        """Submit event to prep input queue (blocking put in thread)."""
        await asyncio.to_thread(self._prep_input_queue.put, event)

    async def stop(self) -> None:
        """Stop prep strategy (no-op for process mode)."""
        pass
