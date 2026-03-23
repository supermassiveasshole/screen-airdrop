"""Sender playback helpers for dump-only and interactive render loops."""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional, Tuple

FrameItem = Dict[str, Any]
FrameNameFunc = Callable[[FrameItem], str]
OverlayFunc = Callable[[FrameItem, bool], str]
RecordFunc = Callable[[FrameItem], None]
RebuildFunc = Callable[[], Tuple[Any, FrameItem]]


def dump_sender_stream(
    frame_generator: Any,
    first_frame: FrameItem,
    *,
    dump_frames: Optional[str],
    frame_name: FrameNameFunc,
    record_item: RecordFunc,
) -> None:
    import cv2

    current_item = first_frame
    while True:
        if dump_frames:
            dump_name = frame_name(current_item)
            cv2.imwrite(os.path.join(dump_frames, dump_name), current_item["image"])
        record_item(current_item)
        try:
            current_item = next(frame_generator)
        except StopIteration:
            break


def render_sender_stream(
    frame_generator: Any,
    first_frame: FrameItem,
    *,
    dump_frames: Optional[str],
    renderer: Any,
    frame_name: FrameNameFunc,
    overlay_for_item: OverlayFunc,
    record_item: RecordFunc,
    rebuild_stream: RebuildFunc,
    update_window_title: Callable[[bool], None],
) -> bool:
    current_item = first_frame
    last_dump_name = None  # type: Optional[str]
    paused = True
    stopped_by_user = False
    update_window_title(True)
    while not stopped_by_user:
        if dump_frames:
            dump_name = frame_name(current_item)
            if dump_name != last_dump_name:
                renderer.cv2.imwrite(os.path.join(dump_frames, dump_name), current_item["image"])
                last_dump_name = dump_name
        command = renderer.show(
            current_item["image"],
            overlay_text=overlay_for_item(current_item, paused),
            pace=not paused,
        )
        if command == "quit":
            stopped_by_user = True
            break
        if command == "reset":
            frame_generator, first_frame = rebuild_stream()
            current_item = first_frame
            paused = True
            last_dump_name = None
            renderer.reset_clock()
            update_window_title(True)
            print("sender reset: replaying from first sync frame")
            continue
        if command == "toggle_pause":
            paused = not paused
            renderer.reset_clock()
            update_window_title(paused)
            if paused:
                print("sender paused")
            else:
                print("sender started")
            continue
        if paused:
            continue

        record_item(current_item)
        try:
            current_item = next(frame_generator)
        except StopIteration:
            frame_generator, first_frame = rebuild_stream()
            current_item = first_frame
            last_dump_name = None
            renderer.reset_clock()
    return stopped_by_user
