"""Sender controller: orchestrate sender frame-stream playback and reporting."""

from __future__ import annotations

import os
import random
from typing import Any, Dict, Optional

from screen_airdrop.common.transport.protocol_basic import ECC_Q
from screen_airdrop.sender.application.frame_stream import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    build_encoded_frames,
)
from screen_airdrop.sender.application.playback import dump_sender_stream, render_sender_stream
from screen_airdrop.sender.application.presentation import (
    frame_name_for_item,
    overlay_text_for_item,
    window_title_for_state,
)
from screen_airdrop.sender.application.reporting import build_sender_report, write_sender_report
from screen_airdrop.sender.application.runtime_state import SenderRuntimeState
from screen_airdrop.sender.render.renderer_cv2 import CV2Renderer
from screen_airdrop.sender.scheduling.broadcast_schedule import BroadcastSchedule


def _mkdir(path: str) -> None:
    if path and not os.path.exists(path):
        os.makedirs(path)


def run_sender(
    input_path: str,
    block_size: int = 6,
    chunk_size: Optional[int] = None,
    chunk_fill_ratio: float = 0.9,
    fps: int = 12,
    compress: str = "gzip",
    sync_frames: int = 8,
    manifest_repeat: int = 5,
    max_epochs: int = 0,
    window_name: str = "screen-airdrop",
    dump_frames: Optional[str] = None,
    report_json: Optional[str] = None,
    overlay: bool = False,
    protocol: str = "basic",
    quiet_zone_px: int = 48,
    ecc_level: str = ECC_Q,
    module_grid: str = "160x96",
    guard_band_modules: int = 2,
    corner_size_modules: int = 9,
    outer_padding_px: int = 0,
    outer_padding_color: str = "black",
    stats_interval: float = 1.0,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    schedule: Optional[BroadcastSchedule] = None,
    dump_only: bool = False,
    emit_coded_units: bool = False,
    coded_redundancy_count: int = 0,
    coded_degree: int = 2,
) -> int:
    if outer_padding_color.lower() not in ("black", "white"):
        raise RuntimeError("invalid outer-padding-color: {0}".format(outer_padding_color))
    session_id = random.getrandbits(64)
    schedule = schedule or BroadcastSchedule(
        sync_frames=sync_frames,
        control_burst_repeat=manifest_repeat,
    )

    def _build_sender_stream():
        stream = build_encoded_frames(
            input_path=input_path,
            block_size=block_size,
            chunk_size=chunk_size,
            chunk_fill_ratio=chunk_fill_ratio,
            compress=compress,
            sync_frames=sync_frames,
            manifest_repeat=manifest_repeat,
            epochs=max_epochs,
            width=width,
            height=height,
            session_id=session_id,
            protocol=protocol,
            quiet_zone_px=quiet_zone_px,
            ecc_level=ecc_level,
            module_grid=module_grid,
            guard_band_modules=guard_band_modules,
            corner_size_modules=corner_size_modules,
            outer_padding_px=outer_padding_px,
            outer_padding_color=outer_padding_color,
            schedule=schedule,
            window_name=window_name,
            emit_coded_units=emit_coded_units,
            coded_redundancy_count=coded_redundancy_count,
            coded_degree=coded_degree,
        )
        first = next(stream)
        return stream, first

    frame_generator, first_frame = _build_sender_stream()
    metadata = first_frame["metadata"]
    session_id = int(metadata["session_id"])
    payload = metadata["payload"]
    payload_chunks = list(metadata["payload_chunks"])
    total_data_frames = int(metadata["total_data_frames"])
    frame_payload_cap = int(metadata["frame_payload_cap"])
    effective_chunk_size = int(metadata.get("effective_chunk_size", chunk_size))
    schedule_meta = dict(metadata.get("schedule", {}))
    control_plane_meta = list(metadata.get("control_plane", []))
    sync_frames = int(schedule_meta.get("sync_frames", schedule.sync_frames))
    control_burst_repeat = int(
        schedule_meta.get("control_burst_repeat", schedule.control_burst_repeat)
    )
    data_realizations = int(schedule_meta.get("data_realizations", schedule.data_realizations))
    payload_chunk_count = int(metadata.get("payload_chunk_count", len(payload_chunks)))
    payload_frame_count = int(metadata.get("payload_frame_count", len(payload_chunks)))
    layered_profiles = {
        key: metadata[key]
        for key in (
            "bootstrap_profile_id",
            "bootstrap_ecc_profile_id",
            "body_profile_id",
            "body_ecc_profile_id",
        )
        if key in metadata
    }

    stopped_by_user = False

    def _control_summary() -> str:
        return ",".join(
            "{0}/{1}".format(
                str(item.get("family", "control")),
                str(item.get("kind", "unknown")),
            )
            for item in control_plane_meta
        )
    runtime_state = SenderRuntimeState(
        protocol=protocol,
        session_id=session_id,
        payload_size=len(payload),
        payload_chunk_count=len(payload_chunks),
        frame_payload_cap=frame_payload_cap,
        effective_chunk_size=effective_chunk_size,
        fps=fps,
        stats_interval=stats_interval,
        control_summary=_control_summary(),
        data_realizations=data_realizations,
    )
    runtime_state.print_session_summary()

    def _record_item(item: Dict[str, Any]) -> None:
        runtime_state.record_item(item)

    def _update_window_title(paused: bool) -> None:
        renderer.set_window_title(window_title_for_state(paused))

    if dump_frames:
        _mkdir(dump_frames)

    if dump_only:
        dump_sender_stream(
            frame_generator,
            first_frame,
            dump_frames=dump_frames,
            frame_name=frame_name_for_item,
            record_item=_record_item,
        )
    else:
        renderer = CV2Renderer(window_name=window_name, fps=fps, show_overlay=overlay)
        try:
            stopped_by_user = render_sender_stream(
                frame_generator,
                first_frame,
                dump_frames=dump_frames,
                renderer=renderer,
                frame_name=frame_name_for_item,
                overlay_for_item=lambda item, paused: overlay_text_for_item(
                    item,
                    paused=paused,
                    session_id=session_id,
                    sync_frames=sync_frames,
                    total_data_frames=total_data_frames,
                    effective_chunk_size=effective_chunk_size,
                    control_burst_repeat=control_burst_repeat,
                    control_summary=_control_summary(),
                    data_realizations=data_realizations,
                ),
                record_item=_record_item,
                rebuild_stream=_build_sender_stream,
                update_window_title=_update_window_title,
            )
        finally:
            renderer.close()

    elapsed, observed_payload_kibps = runtime_state.finish()

    report = build_sender_report(
        session_id=session_id,
        protocol=protocol,
        layered_profiles=layered_profiles,
        sent_frames=runtime_state.sent_frames,
        sent_data_frames=runtime_state.sent_data_frames,
        elapsed=elapsed,
        effective_chunk_size=effective_chunk_size,
        payload_chunk_count=payload_chunk_count,
        payload_frame_count=payload_frame_count,
        data_realizations=data_realizations,
        theoretical_payload_kibps=runtime_state.theoretical_payload_kibps,
        observed_payload_kibps=observed_payload_kibps,
        stopped_by_user=stopped_by_user,
        dump_only=dump_only,
        control_plane_meta=control_plane_meta,
        control_summary=_control_summary(),
        emit_coded_units=bool(metadata.get("emit_coded_units", False)),
        coded_redundancy_count=int(metadata.get("coded_redundancy_count", 0)),
        coded_degree=int(metadata.get("coded_degree", 0)),
        coded_scheme=str(metadata.get("coded_scheme", "")),
        coded_units_emitted=int(metadata.get("coded_unit_count", 0)),
        coded_generations_skipped=sum(
            1
            for plan in metadata.get("systematic_generations", [])
            if str(plan.get("coded_emission_mode", "")).startswith("skipped_")
        ),
        systematic_generations=list(metadata.get("systematic_generations", [])),
    )
    write_sender_report(report_json, report)

    return 0
