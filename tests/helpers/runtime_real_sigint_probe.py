from __future__ import annotations

import json
import signal
import sys
import time
from multiprocessing import resource_tracker

from screen_airdrop.receiver.information.assembler import ChunkAssembler
from screen_airdrop.receiver.runtime.screen_capture import ScreenCapture
from screen_airdrop.receiver.pipeline.live import ScreenLiveRuntime


def main() -> None:
    capture = ScreenCapture(
        window_title=None,
        region=(0, 0, 128, 128),
        monitor_index=1,
        frame_diff_threshold=0.0,
        target_fps=10.0,
    )
    runtime = ScreenLiveRuntime(
        capture=capture,
        assembler=ChunkAssembler(),
        protocol="layered",
        decode_workers=2,
        capture_fps=10.0,
        prep_process=1,
        manual_mode=True,
        initial_search_roi=(0, 0, 128, 128),
    )
    runtime.start()

    child_pids = []
    for proc in [
        runtime._grab_process,
        runtime._prep_process,
        *runtime._decode_processes,
        runtime._dump_process,
    ]:
        if proc is not None and proc.pid is not None:
            child_pids.append(proc.pid)

    payload = {
        "child_pids": child_pids,
        "resource_tracker_pid": getattr(resource_tracker._resource_tracker, "_pid", None),
    }
    print(json.dumps(payload), flush=True)

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        runtime.stop()
        runtime.join()

    sys.exit(130)


if __name__ == "__main__":
    main()
