from __future__ import annotations

import json
import multiprocessing as mp
import signal
import sys
import time
from multiprocessing import resource_tracker, shared_memory
from threading import Lock
from typing import Any, Dict, List, cast

from screen_airdrop.receiver.pipeline.live import ScreenLiveRuntime


def _child_block_on_queue(q: Any) -> None:
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except Exception:
        pass
    while True:
        item = q.get()
        if item is None:
            break
        time.sleep(0.05)


def _build_runtime() -> tuple[ScreenLiveRuntime, List[Any], int | None]:
    ctx = mp.get_context("spawn")
    runtime = object.__new__(ScreenLiveRuntime)
    runtime_any = cast(Any, runtime)
    runtime_any._shutdown_lock = Lock()
    runtime_any._shutdown_complete = False
    runtime_any._stop_event = type("_Dummy", (), {"set": lambda self: None})()
    runtime_any._proc_stop_event = ctx.Event()
    runtime_any._grab_slot_queue = ctx.SimpleQueue()
    runtime_any._grab_event_queue = ctx.SimpleQueue()
    runtime_any._prep_input_queue = ctx.SimpleQueue()
    runtime_any._prep_output_queue = ctx.SimpleQueue()
    runtime_any._decode_assignment_queues = [ctx.SimpleQueue(), ctx.SimpleQueue()]
    runtime_any._decode_result_queue = ctx.SimpleQueue()
    runtime_any._dump_queue = ctx.SimpleQueue()
    runtime_any._dump_event_queue = ctx.SimpleQueue()
    runtime_any._slots = [shared_memory.SharedMemory(create=True, size=1)]
    runtime_any._grab_process = ctx.Process(
        target=_child_block_on_queue,
        args=(runtime_any._grab_slot_queue,),
        daemon=False,
        name="SigintProbeGrab",
    )
    runtime_any._prep_process = ctx.Process(
        target=_child_block_on_queue,
        args=(runtime_any._prep_input_queue,),
        daemon=False,
        name="SigintProbePrep",
    )
    runtime_any._decode_processes = [
        ctx.Process(
            target=_child_block_on_queue,
            args=(runtime_any._decode_assignment_queues[0],),
            daemon=False,
            name="SigintProbeDecode0",
        ),
        ctx.Process(
            target=_child_block_on_queue,
            args=(runtime_any._decode_assignment_queues[1],),
            daemon=False,
            name="SigintProbeDecode1",
        ),
    ]
    runtime_any._dump_process = ctx.Process(
        target=_child_block_on_queue,
        args=(runtime_any._dump_queue,),
        daemon=False,
        name="SigintProbeDump",
    )
    procs = [
        runtime_any._grab_process,
        runtime_any._prep_process,
        *runtime_any._decode_processes,
        runtime_any._dump_process,
    ]
    for proc in procs:
        proc.start()
    tracker_pid = getattr(resource_tracker._resource_tracker, "_pid", None)
    return runtime, procs, tracker_pid


def main() -> None:
    runtime, procs, tracker_pid = _build_runtime()
    payload: Dict[str, List[int] | int | None] = {
        "child_pids": [proc.pid for proc in procs if proc.pid is not None],
        "resource_tracker_pid": tracker_pid,
    }
    print(json.dumps(payload), flush=True)

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        ScreenLiveRuntime.stop(runtime)
        ScreenLiveRuntime._shutdown_processes(runtime)

    sys.exit(130)


if __name__ == "__main__":
    main()
