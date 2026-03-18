"""Runtime coordinator: pure event router."""

import asyncio
import threading
from typing import Any, List, Optional

from screen_airdrop.receiver.assembler import ChunkAssembler
from screen_airdrop.receiver.reporting import ReportCollector
from screen_airdrop.receiver.runtime.events import (
    DecodeAssignment,
    DecodeCompletion,
    DumpCopyCompletion,
    DuplicateSlotEvent,
    FilledSlotEvent,
    PreparedSlotEvent,
)
from screen_airdrop.receiver.runtime.geometry_tracker import GeometryTracker
from screen_airdrop.receiver.runtime.prep_strategy import PrepStrategy
from screen_airdrop.receiver.runtime.slot_manager import SlotManager
from screen_airdrop.receiver.runtime.stats import ScreenLiveRuntimeStats

_GRAB_OWNER = "grab"


class RuntimeCoordinator:
    """Pure event router: receives events from workers, dispatches to handlers."""

    def __init__(
        self,
        *,
        slot_manager: SlotManager,
        geometry_tracker: GeometryTracker,
        stats: ScreenLiveRuntimeStats,
        assembler: ChunkAssembler,
        report_collector: ReportCollector,
        prep_strategy: PrepStrategy,
        grab_slot_queue: Any,
        grab_event_queue: Any,
        prep_output_queue: Optional[Any],
        decode_assignment_queues: List[Any],
        decode_result_queue: Any,
        dump_queue: Optional[Any],
        dump_event_queue: Optional[Any],
        stop_event: threading.Event,
        stream_id: str,
        on_frame_callback: Optional[Any] = None,
    ):
        """Initialize coordinator.

        Args:
            slot_manager: Slot lifecycle manager
            geometry_tracker: Geometry state tracker
            stats: Runtime statistics
            assembler: Chunk assembler
            report_collector: ReportCollector for new architecture
            prep_strategy: Prep processing strategy (async or process)
            grab_slot_queue: Queue for slot assignments to grab worker
            grab_event_queue: Queue for filled slot events from grab worker
            prep_output_queue: Queue for prep results (None if async prep)
            decode_assignment_queues: List of queues for decode workers
            decode_result_queue: Queue for decode results
            dump_queue: Queue for dump requests (None if no dump)
            dump_event_queue: Queue for dump completion events (None if no dump)
            stop_event: Event to signal shutdown
            stream_id: Stream identifier
            on_frame_callback: Optional callback for frame events
        """
        self._slot_manager = slot_manager
        self._geometry_tracker = geometry_tracker
        self._stats = stats
        self._assembler = assembler
        self._report_collector = report_collector
        self._prep_strategy = prep_strategy
        self._grab_slot_queue = grab_slot_queue
        self._grab_event_queue = grab_event_queue
        self._prep_output_queue = prep_output_queue
        self._decode_assignment_queues = decode_assignment_queues
        self._decode_result_queue = decode_result_queue
        self._dump_queue = dump_queue
        self._dump_event_queue = dump_event_queue
        self._stop_event = stop_event
        self._stream_id = stream_id
        self._on_frame_callback = on_frame_callback

        # Internal state
        self._next_worker = 0
        self._coord_queue: Optional[asyncio.Queue] = None
        self._last_fingerprint: Optional[bytes] = None

    async def run(self) -> None:
        """Run coordinator event loop."""
        self._coord_queue = asyncio.Queue()

        # Start prep strategy
        await self._prep_strategy.start(self._coord_queue)

        # Start independent event processing tasks
        tasks = [
            asyncio.create_task(self._process_grab_events()),
            asyncio.create_task(self._process_decode_events()),
        ]

        # Add prep task based on mode
        if self._prep_output_queue is not None:
            # Process mode: read from prep_output_queue
            tasks.append(asyncio.create_task(self._process_prep_events_process()))
        else:
            # Async mode: read from coord_queue
            tasks.append(asyncio.create_task(self._process_prep_events_async()))

        if self._dump_event_queue is not None:
            tasks.append(asyncio.create_task(self._process_dump_events()))

        try:
            # Wait for any task to complete (decode task will exit when assembly complete)
            # Use return_when=FIRST_COMPLETED to exit as soon as decode task finishes
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

            # If decode task completed due to assembly complete, cancel all other tasks immediately
            if self._stop_event.is_set():
                for task in pending:
                    task.cancel()
                # Don't wait for cancellations - just let them be cancelled
            else:
                # Some other task completed unexpectedly, wait for all
                await asyncio.gather(*tasks)
        finally:
            # Cancel all remaining tasks to ensure clean shutdown
            for task in tasks:
                if not task.done():
                    task.cancel()
            # Wait for cancellations to complete
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=1.0
                )
            except asyncio.TimeoutError:
                pass  # Force exit even if tasks don't cancel quickly
            # Cleanup
            await self._prep_strategy.stop()

    async def _process_grab_events(self) -> None:
        """Process grab events independently."""
        while not self._stop_event.is_set():
            item = await asyncio.to_thread(self._grab_event_queue.get)
            if item is None:
                break
            await self._handle_grab_event(item)

    async def _process_prep_events_async(self) -> None:
        """Process prep events (async mode) from coord_queue."""
        assert self._coord_queue is not None
        while not self._stop_event.is_set():
            source, item = await self._coord_queue.get()
            if source != "prep":
                continue
            if item is None:
                break
            self._handle_prep_result(item)

    async def _process_prep_events_process(self) -> None:
        """Process prep events (process mode) from prep_output_queue."""
        assert self._prep_output_queue is not None
        while not self._stop_event.is_set():
            item = await asyncio.to_thread(self._prep_output_queue.get)
            if item is None:
                break
            self._handle_prep_result(item)

    async def _process_decode_events(self) -> None:
        """Process decode events independently."""
        while not self._stop_event.is_set():
            item = await asyncio.to_thread(self._decode_result_queue.get)
            if item is None:
                break
            self._handle_decode_result(item)

            # Check if assembly complete
            if self._assembler.complete():
                # Assembly complete - stop everything immediately
                self._stop_event.set()

                # Send sentinel values to unblock all queue.get() calls
                # This ensures other tasks exit quickly
                try:
                    self._grab_event_queue.put_nowait(None)
                except Exception:
                    pass

                if self._prep_output_queue is not None:
                    try:
                        self._prep_output_queue.put_nowait(None)
                    except Exception:
                        pass

                if self._dump_event_queue is not None:
                    try:
                        self._dump_event_queue.put_nowait(None)
                    except Exception:
                        pass

                # Exit immediately - processes will be terminated in shutdown
                break

    async def _process_dump_events(self) -> None:
        """Process dump events independently."""
        assert self._dump_event_queue is not None
        while not self._stop_event.is_set():
            item = await asyncio.to_thread(self._dump_event_queue.get)
            if item is None:
                break
            self._handle_dump_result(item)

    async def _handle_grab_event(self, event: object) -> None:
        """Handle grab event (filled slot)."""
        if event is None:
            return

        # Handle error events
        if isinstance(event, dict) and event.get("kind") == "error":
            raise RuntimeError(f"grab process failed: {event.get('error', '')}")

        # Handle slot starvation events
        if isinstance(event, dict) and event.get("kind") == "grab_slot_starvation":
            with self._stats._lock:
                self._stats.slot_starvation_events += 1
                self._stats.dropped_slot_starvation += 1
            # Note: We don't force-release slots here to keep the implementation simple
            # The grab thread will continue grabbing and updating raw_grab_frames
            # This allows us to observe the true grab rate vs captured rate
            return

        # Handle raw grab stats (before slot assignment)
        if isinstance(event, dict) and event.get("kind") == "raw_grab_stats":
            with self._stats._lock:
                self._stats.raw_grab_frames += 1
                self._stats.capture_grab_time_ms += float(event.get("grab_ms", 0.0) or 0.0)
                self._stats.capture_grab_ops += 1
            return

        # Handle slot wait metrics
        if isinstance(event, dict) and event.get("kind") == "slot_wait_ms":
            with self._stats._lock:
                self._stats.slot_wait_ms += float(event.get("value", 0.0) or 0.0)
                self._stats.slot_wait_ops += 1
            return

        # Handle filled slot event
        if not isinstance(event, FilledSlotEvent):
            return

        descriptor = event.descriptor

        # Mark slot as filled
        if not self._slot_manager.mark_filled(descriptor, _GRAB_OWNER):
            return

        # Update stats
        # - raw_grab_frames: total grabs (including starvation)
        # - captured: successful slot assignments
        with self._stats._lock:
            self._stats.raw_grab_frames += 1  # Count every grab
            self._stats.captured += 1          # Count successful slot assignment
            self._stats.capture_grab_time_ms += float(event.grab_ms)
            self._stats.capture_grab_ops += 1
            self._stats.capture_copy_time_ms += float(event.copy_ms)
            self._stats.capture_copy_ops += 1
            self._stats.capture_overwrite_count = (
                self._slot_manager.snapshot_overwrite_count()
            )
            self._stats.capture_overwrite_before_prep = (
                self._slot_manager.snapshot_overwrite_before_prep_count()
            )

        # Send to prep strategy
        await self._prep_strategy.submit(event)

    def _handle_prep_result(self, item: object) -> None:
        """Handle prep result (fingerprint + dedup decision)."""
        from screen_airdrop.receiver.runtime.events import PrepFingerprintEvent
        from screen_airdrop.receiver.runtime.frame_preprocessor import fingerprint_diff

        if item is None:
            return

        # Handle error events
        if isinstance(item, dict) and item.get("kind") == "error":
            raise RuntimeError(f"prep stage failed: {item.get('error', '')}")

        # Handle prep_skip events (single frame error)
        if isinstance(item, dict) and item.get("kind") == "prep_skip":
            descriptor = item.get("descriptor")
            if descriptor is not None:
                self._slot_manager.mark_duplicate_and_release(descriptor)
                self._dispatch_slot_to_grab()
            return

        # Handle PrepFingerprintEvent (from process mode) or PreparedSlotEvent/DuplicateSlotEvent (from async mode)
        if isinstance(item, PrepFingerprintEvent):
            # Process mode: need to do dedup here
            descriptor = item.descriptor
            if not self._slot_manager.descriptor_matches_current(descriptor):
                return

            # Check for duplicate
            dedup_score = fingerprint_diff(item.fingerprint, self._last_fingerprint)

            with self._stats._lock:
                self._stats.prep_processed_frames += 1
                self._stats.fingerprint_time_ms += item.fingerprint_ms
                self._stats.fingerprint_ops += 1
                self._stats.dedup_decision_ms += 0.0
                self._stats.dedup_decision_ops += 1

            if dedup_score < 0.015:  # Duplicate threshold
                # Duplicate frame
                self._slot_manager.mark_duplicate_and_release(descriptor)
                self._dispatch_slot_to_grab()
                with self._stats._lock:
                    self._stats.duplicate_frames += 1
                return

            # New frame
            self._last_fingerprint = item.fingerprint
            # Continue to decode assignment below

        elif isinstance(item, DuplicateSlotEvent):
            # Async mode: duplicate
            self._slot_manager.mark_duplicate_and_release(item.descriptor)
            self._dispatch_slot_to_grab()

            with self._stats._lock:
                self._stats.duplicate_frames += 1
                self._stats.prep_processed_frames += 1
                self._stats.fingerprint_time_ms += item.fingerprint_ms
                self._stats.fingerprint_ops += 1
                self._stats.dedup_decision_ms += item.dedup_decision_ms
                self._stats.dedup_decision_ops += 1
            return

        elif isinstance(item, PreparedSlotEvent):
            # Async mode: prepared (non-duplicate)
            descriptor = item.descriptor
            with self._stats._lock:
                self._stats.prep_processed_frames += 1
                self._stats.fingerprint_time_ms += item.fingerprint_ms
                self._stats.fingerprint_ops += 1
                self._stats.dedup_decision_ms += item.dedup_decision_ms
                self._stats.dedup_decision_ops += 1

        else:
            return

        # Build decode assignment (for non-duplicate frames)
        if isinstance(item, PrepFingerprintEvent):
            descriptor = item.descriptor
        elif isinstance(item, PreparedSlotEvent):
            descriptor = item.descriptor
        else:
            return

        assignment = self._build_assignment(descriptor)

        # Dispatch to decode worker
        worker_id = self._next_worker
        self._next_worker = (self._next_worker + 1) % len(
            self._decode_assignment_queues
        )

        try:
            self._decode_assignment_queues[worker_id].put(assignment)
            with self._stats._lock:
                self._stats.accepted_for_decode_frames += 1
                self._stats.decode_queue_depth += 1
                self._stats.decode_queue_depth_peak = max(
                    self._stats.decode_queue_depth_peak,
                    self._stats.decode_queue_depth,
                )
        except Exception:
            with self._stats._lock:
                self._stats.dropped_queue_full += 1

            # Send to dump if requested
            if self._dump_queue is not None and item.descriptor.dump_requested:
                if self._slot_manager.set_dump_reader(item.descriptor):
                    try:
                        self._dump_queue.put(item.descriptor)
                    except Exception:
                        self._slot_manager.clear_dump_reader(item.descriptor)
                        with self._stats._lock:
                            self._stats.dropped_dump_backpressure += 1

    def _build_assignment(self, descriptor: Any) -> DecodeAssignment:
        """Build decode assignment."""
        worker_id = self._next_worker
        self._slot_manager.assign_decode(descriptor, worker_id)

        return DecodeAssignment(
            descriptor=descriptor,
            stream_id=self._stream_id,
            geometry_generation=self._geometry_tracker.current_generation,
            decode_owner=f"decode:{worker_id}",
            dump_requested=descriptor.dump_requested,
            geometry_state=self._geometry_tracker.current_geometry,
            forced_roi=self._geometry_tracker.get_current_roi(),
        )

    def _handle_decode_result(self, item: object) -> None:
        """Handle decode result."""

        if item is None:
            return

        if not isinstance(item, DecodeCompletion):
            return

        with self._stats._lock:
            self._stats.decode_queue_depth = max(
                0, self._stats.decode_queue_depth - 1
            )

        if item.success:
            self._handle_decode_completion(item)
        else:
            self._handle_decode_failure(item)

    def _handle_decode_completion(self, completion: Any) -> None:
        """Handle successful decode."""
        # Update stats
        with self._stats._lock:
            self._stats.decode_ok += 1
            self._stats.ipc_recv_time_ms += completion.decode_attach_ms
            self._stats.ipc_recv_ops += 1

            # Track geometry mode
            if completion.decode_mode == "geometry_reuse":
                self._stats.lock_decode_mode_geometry_reuse += 1
                self._stats.geometry_reuse_success_count += 1
            else:
                self._stats.lock_decode_mode_reacquire_locator += 1
                self._stats.reacquire_success_count += 1

            # Track first frames
            if self._stats.first_valid_frame_ts is None:
                self._stats.first_valid_frame_ts = completion.descriptor.ts

            if (
                completion.frame_type == 1
                and self._stats.first_data_frame_ts is None
            ):  # FRAME_DATA
                self._stats.first_data_frame_ts = completion.descriptor.ts

        # Update geometry
        if (
            self._geometry_tracker.lock_mode != "locked"
            and completion.proposed_geometry_state is not None
        ):
            self._geometry_tracker.propose_update(
                proposed_geometry=completion.proposed_geometry_state,
                decode_quality=completion.decode_quality,
                used_geometry_generation=completion.used_geometry_generation,
            )

        # Extract bbox and update ROI
        bbox = completion.meta.det_bbox if hasattr(completion, "meta") and hasattr(completion.meta, "det_bbox") else None
        self._geometry_tracker.record_success(
            geometry=completion.proposed_geometry_state,
            bbox=bbox,
        )

        # Assemble chunk
        if completion.frame_type == 1:  # FRAME_DATA
            is_new = self._assembler.add(completion.chunk_id, completion.payload)

            with self._stats._lock:
                if is_new:
                    self._stats.decoded_new_chunks += 1
                    self._stats.assembled += 1
                    self._stats.assembled_bytes += len(completion.payload)
                    if self._stats.first_new_chunk_ts is None:
                        self._stats.first_new_chunk_ts = completion.descriptor.ts
                else:
                    self._stats.decoded_duplicate_chunks += 1

        # Complete decode and release slot
        self._slot_manager.complete_decode(completion.descriptor, completion.worker_id)
        self._dispatch_slot_to_grab()

        # Callback
        if self._on_frame_callback is not None:
            self._on_frame_callback(completion)

    def _handle_decode_failure(self, completion: Any) -> None:
        """Handle decode failure."""
        # Get error message
        error = getattr(completion, "error", "unknown error")

        # Extract failure_class from worker (DecodeError attributes)
        failure_class = getattr(completion, "failure_class", "unknown")

        with self._stats._lock:
            self._stats.decode_fail += 1
            self._stats.last_decode_error = error
            self._stats.last_failure_class = failure_class

            # Track failure by class
            if failure_class == "header":
                self._stats.failure_count_header += 1
            elif failure_class == "payload":
                self._stats.failure_count_payload += 1
            elif failure_class == "locator":
                self._stats.failure_count_locator += 1
            else:
                self._stats.failure_count_unknown += 1

            # Track geometry mode
            if completion.decode_mode == "geometry_reuse":
                self._stats.geometry_reuse_fail_count += 1
            else:
                self._stats.reacquire_fail_count += 1

        # Record failure and check if should reacquire
        should_reacquire = self._geometry_tracker.record_failure()

        if should_reacquire:
            with self._stats._lock:
                self._stats.lock_locked_to_acquire += 1

        # Complete decode and release slot
        self._slot_manager.complete_decode(completion.descriptor, completion.worker_id)
        self._dispatch_slot_to_grab()

    def _handle_dump_result(self, item: object) -> None:
        """Handle dump completion."""
        if item is None or not isinstance(item, DumpCopyCompletion):
            return

        self._slot_manager.clear_dump_reader(item.descriptor)
        self._dispatch_slot_to_grab()

        with self._stats._lock:
            if item.copied:
                self._stats.dump_time_ms += item.dump_ms
                self._stats.dump_ops += 1
            else:
                self._stats.dropped_dump_backpressure += 1

    def _dispatch_slot_to_grab(self) -> None:
        """Dispatch a free slot to grab worker."""
        if self._stop_event.is_set():
            return

        allocated = self._slot_manager.allocate_for_grab(_GRAB_OWNER)
        if allocated is None:
            allocated = self._slot_manager.overwrite_oldest_filled(_GRAB_OWNER)

        if allocated is None:
            with self._stats._lock:
                self._stats.dropped_slot_unavailable += 1
            return

        slot_id, generation, _ = allocated

        try:
            self._grab_slot_queue.put((slot_id, generation))
        except Exception:
            with self._stats._lock:
                self._stats.dropped_slot_unavailable += 1
