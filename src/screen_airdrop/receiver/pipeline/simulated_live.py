"""Live-style runtime driven by a pre-generated frames directory."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, Optional

from screen_airdrop.common.transport.protocol_basic import DEFAULT_GRID_H, DEFAULT_GRID_W
from screen_airdrop.receiver.information import ChunkAssembler
from screen_airdrop.receiver.pipeline.live import ScreenLiveRuntime
from screen_airdrop.receiver.runtime.workers import (
    decode_worker_main,
    prep_process_main,
    replay_grab_process_main,
)

__all__ = ["SimulatedLiveRuntime"]


class SimulatedLiveRuntime(ScreenLiveRuntime):
    """Frames-dir producer with live-style queue/worker/coordinator semantics."""

    def __init__(
        self,
        *,
        frame_source,
        assembler: ChunkAssembler,
        protocol: str = "basic",
        grid_w: int = DEFAULT_GRID_W,
        grid_h: int = DEFAULT_GRID_H,
        guard_band: int = 2,
        corner_size: int = 9,
        decode_workers: int = 1,
        frame_queue_size: int = 32,
        result_queue_size: int = 256,
        capture_fps: float = 30.0,
        debug_dir: Optional[str] = None,
        debug_interval: float = 1.0,
        debug_max_frames: int = 30,
        prep_process: int = 0,
        pacing_mode: str = "none",
    ) -> None:
        width, height = frame_source.infer_frame_size()
        synthetic_capture = SimpleNamespace(
            window_title=None,
            region=(0, 0, int(width), int(height)),
            monitor_index=1,
            active_region=(0, 0, int(width), int(height)),
        )
        self._frame_source = frame_source
        self._simulated_live_pacing = str(pacing_mode)
        super().__init__(
            capture=synthetic_capture,
            assembler=assembler,
            protocol=protocol,
            grid_w=grid_w,
            grid_h=grid_h,
            guard_band=guard_band,
            corner_size=corner_size,
            manual_mode=False,
            decode_workers=decode_workers,
            frame_queue_size=frame_queue_size,
            result_queue_size=result_queue_size,
            capture_fps=capture_fps,
            capture_dump_dir=None,
            capture_dump_max_frames=0,
            debug_dir=debug_dir,
            debug_interval=debug_interval,
            debug_max_frames=debug_max_frames,
            prep_process=prep_process,
            initial_search_roi=None,
            on_frame_callback=None,
            pre_resolved_capture_region=(0, 0, int(width), int(height)),
        )
        self._stream_id = "simulated_live:0"

    def snapshot(self) -> Dict[str, Any]:
        snap = super().snapshot()
        snap["runtime_mode"] = "simulated_live"
        snap["producer_mode"] = "frames_dir"
        snap["simulated_live_pacing"] = self._simulated_live_pacing
        return snap

    def _start_processes(self) -> None:
        self._grab_process = self._ctx.Process(
            target=replay_grab_process_main,
            kwargs={
                "slot_assign_queue": self._grab_slot_queue,
                "descriptor_queue": self._grab_event_queue,
                "stop_event": self._proc_stop_event,
                "slot_names": [slot.name for slot in self._slots],
                "width": self._width,
                "height": self._height,
                "frames_dir": self._frame_source.frames_dir,
                "pacing_mode": self._simulated_live_pacing,
                "target_fps": float(self._capture_fps),
            },
            daemon=False,
            name="SimulatedLiveProducer",
        )
        self._grab_process.start()
        if (
            self._prep_processes > 0
            and self._prep_input_queue is not None
            and self._prep_output_queue is not None
        ):
            self._prep_process = self._ctx.Process(
                target=prep_process_main,
                kwargs={
                    "prep_input_queue": self._prep_input_queue,
                    "prep_output_queue": self._prep_output_queue,
                    "slot_names": [slot.name for slot in self._slots],
                    "width": self._width,
                    "height": self._height,
                    "prep_roi": self._prep_roi,
                },
                daemon=False,
                name="SimulatedLivePrep",
            )
            self._prep_process.start()
        for worker_id in range(self._decode_workers):
            proc = self._ctx.Process(
                target=decode_worker_main,
                kwargs={
                    "worker_id": worker_id,
                    "assignment_queue": self._decode_assignment_queues[worker_id],
                    "result_queue": self._decode_result_queue,
                    "slot_names": [slot.name for slot in self._slots],
                    "width": self._width,
                    "height": self._height,
                    "protocol": self._protocol,
                    "grid_w": self._grid_w,
                    "grid_h": self._grid_h,
                    "guard_band": self._guard_band,
                    "corner_size": self._corner_size,
                },
                daemon=False,
                name=f"SimulatedLiveDecode-{worker_id}",
            )
            proc.start()
            self._decode_processes.append(proc)
