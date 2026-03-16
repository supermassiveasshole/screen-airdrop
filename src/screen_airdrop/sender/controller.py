"""Sender controller: package input, encode chunks, and broadcast frames in epochs."""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import asdict
from typing import Any, Dict, Generator, Optional

from screen_airdrop.common.control_plane import (
    CONTROL_FAMILY_BOOTSTRAP,
    CONTROL_FAMILY_GENERATION,
    CONTROL_KIND_GENERATION,
    CONTROL_KIND_LAYOUT,
    CONTROL_KIND_MANIFEST,
    CONTROL_KIND_SESSION,
    CONTROL_WIRE_CHUNK_IDS,
    ControlPlaneItem,
    encode_generation_control,
    encode_layout_bootstrap,
    encode_session_bootstrap,
)
from screen_airdrop.common.manifest import Manifest
from screen_airdrop.common.packing import build_payload_and_manifest
from screen_airdrop.common.protocol_basic import (
    ECC_LEVELS,
    ECC_Q,
    FRAME_DATA,
    FRAME_END,
    FRAME_SYNC,
    FrameHeaderBasic,
)
from screen_airdrop.sender.protocol_adapter_basic import BasicProtocolEncoder
from screen_airdrop.sender.protocol_adapter_compact import CompactProtocolEncoder
from screen_airdrop.sender.protocol_adapter_gray4 import Gray4ProtocolEncoder
from screen_airdrop.sender.renderer_cv2 import CV2Renderer
from screen_airdrop.sender.schedule_policy import BroadcastSchedule

DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080


def _mkdir(path: str) -> None:
    if path and not os.path.exists(path):
        os.makedirs(path)


def _build_chunks(
    input_path: str,
    compress: str,
    chunk_size: int,
    session_id: int,
) -> Dict[str, Any]:
    payload, manifest, payload_chunks = build_payload_and_manifest(
        input_path=input_path,
        compress_method=compress,
        chunk_size=chunk_size,
        session_id=session_id,
    )
    manifest_bytes = manifest.to_json_bytes()
    if len(manifest_bytes) > int(chunk_size):
        compact = Manifest(
            protocol_version=manifest.protocol_version,
            session_id=manifest.session_id,
            created_at=manifest.created_at,
            input_root_name=manifest.input_root_name,
            pack=manifest.pack,
            compress=manifest.compress,
            chunk_size=manifest.chunk_size,
            total_chunks=manifest.total_chunks,
            payload_size=manifest.payload_size,
            payload_sha256=manifest.payload_sha256,
            entries=[],
        )
        manifest_bytes = compact.to_json_bytes()
    if len(manifest_bytes) > int(chunk_size):
        mini = {
            "v": manifest.protocol_version,
            "sid": manifest.session_id,
            "at": manifest.created_at,
            "root": manifest.input_root_name,
            "pk": manifest.pack,
            "cp": manifest.compress,
            "cs": manifest.chunk_size,
            "tc": manifest.total_chunks,
            "ps": manifest.payload_size,
            "sha": manifest.payload_sha256,
        }
        manifest_bytes = json.dumps(mini, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if len(manifest_bytes) > int(chunk_size):
        raise RuntimeError("manifest chunk too large even in mini format")
    control_items = [
        ControlPlaneItem(
            kind=CONTROL_KIND_MANIFEST,
            payload=manifest_bytes,
            wire_chunk_id=CONTROL_WIRE_CHUNK_IDS[CONTROL_KIND_MANIFEST],
        )
    ]
    return {
        "payload": payload,
        "manifest": manifest,
        "control_items": control_items,
        "payload_chunks": payload_chunks,
    }


def _build_layout_control_payload(
    *,
    protocol: str,
    layout_info: Any,
    ecc_level: str,
    frame_payload_cap: int,
    effective_chunk_size: int,
    module_grid: str,
) -> bytes:
    return encode_layout_bootstrap(
        {
            "protocol": protocol,
            "protocol_version": getattr(layout_info, "protocol_version", ""),
            "frame_w": int(getattr(layout_info, "frame_w", 0)),
            "frame_h": int(getattr(layout_info, "frame_h", 0)),
            "grid_w": int(getattr(layout_info, "grid_w", 0)),
            "grid_h": int(getattr(layout_info, "grid_h", 0)),
            "bits_per_module": int(getattr(layout_info, "bits_per_module", 0)),
            "guard_band": int(getattr(layout_info, "guard_band", 0)),
            "quiet_zone": int(getattr(layout_info, "quiet_zone", 0)),
            "finder_size": int(getattr(layout_info, "finder_size", 0)),
            "ecc_level": ecc_level,
            "frame_payload_cap": int(frame_payload_cap),
            "effective_chunk_size": int(effective_chunk_size),
            "module_grid": module_grid,
        }
    )


def _build_session_control_payload(
    *,
    session_id: int,
    manifest: Manifest,
    protocol: str,
    window_name: Optional[str],
) -> bytes:
    return encode_session_bootstrap(
        {
            "session_id": int(session_id),
            "protocol": protocol,
            "protocol_version": int(manifest.protocol_version),
            "created_at": manifest.created_at,
            "input_root_name": manifest.input_root_name,
            "pack": manifest.pack,
            "compress": manifest.compress,
            "window_name": "" if window_name is None else str(window_name),
        }
    )


def _build_generation_control_payload(
    *,
    generation_id: int,
    total_frames: int,
    payload_chunk_count: int,
    effective_chunk_size: int,
    protocol: str,
) -> bytes:
    return encode_generation_control(
        {
            "generation_id": int(generation_id),
            "total_frames": int(total_frames),
            "payload_chunk_count": int(payload_chunk_count),
            "effective_chunk_size": int(effective_chunk_size),
            "protocol": protocol,
        }
    )


def build_encoded_frames(
    input_path: str,
    block_size: int = 6,
    chunk_size: Optional[int] = None,
    chunk_fill_ratio: float = 0.9,
    compress: str = "gzip",
    sync_frames: int = 8,
    manifest_repeat: int = 5,
    epochs: int = 1,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    session_id: Optional[int] = None,
    protocol: str = "basic",
    quiet_zone_px: int = 48,
    ecc_level: str = ECC_Q,
    module_grid: str = "160x96",
    guard_band_modules: int = 2,
    corner_size_modules: int = 9,
    outer_padding_px: int = 0,
    outer_padding_color: str = "black",
    schedule: Optional[BroadcastSchedule] = None,
    window_name: Optional[str] = None,
) -> Generator[Dict[str, Any], None, None]:
    if session_id is None:
        session_id = random.getrandbits(64)
    outer_padding_white = outer_padding_color.lower() == "white"
    schedule = schedule or BroadcastSchedule(
        sync_frames=sync_frames,
        control_burst_repeat=manifest_repeat,
    )

    gw = 160
    gh = 96
    encoder = None
    if protocol == "basic":
        if ecc_level not in ECC_LEVELS:
            raise RuntimeError("invalid ecc-level: {0}".format(ecc_level))
        try:
            gw, gh = [int(p) for p in module_grid.lower().split("x")]
        except Exception as exc:
            raise RuntimeError("invalid module-grid {0}: {1}".format(module_grid, exc))
        version = 1  # basic protocol

        # Create protocol encoder
        encoder = BasicProtocolEncoder(
            grid_w=gw,
            grid_h=gh,
            ecc_level=ecc_level,
            guard_band=guard_band_modules,
            corner_size=corner_size_modules,
            outer_padding_px=outer_padding_px,
            outer_padding_white=outer_padding_white,
        )
        layout_info = encoder.get_layout()
        cap = layout_info.data_capacity_bits // 8
    elif protocol == "compact":
        if ecc_level not in ECC_LEVELS:
            raise RuntimeError("invalid ecc-level: {0}".format(ecc_level))
        try:
            gw, gh = [int(p) for p in module_grid.lower().split("x")]
        except Exception as exc:
            raise RuntimeError("invalid module-grid {0}: {1}".format(module_grid, exc))
        version = 1  # compact protocol

        # Create compact protocol encoder
        encoder = CompactProtocolEncoder(
            grid_w=gw,
            grid_h=gh,
            ecc_level=ecc_level,
            guard_band=1,  # Compact default
            corner_size=7,  # Compact default
            outer_padding_px=outer_padding_px,
            outer_padding_white=outer_padding_white,
        )
        layout_info = encoder.get_layout()
        cap = layout_info.data_capacity_bits // 8
    elif protocol == "gray4":
        if ecc_level not in ECC_LEVELS:
            raise RuntimeError("invalid ecc-level: {0}".format(ecc_level))
        try:
            gw, gh = [int(p) for p in module_grid.lower().split("x")]
        except Exception as exc:
            raise RuntimeError("invalid module-grid {0}: {1}".format(module_grid, exc))
        version = 1  # gray4 protocol

        # Create gray4 protocol encoder
        encoder = Gray4ProtocolEncoder(
            grid_w=gw,
            grid_h=gh,
            ecc_level=ecc_level,
            guard_band=guard_band_modules,
            corner_size=corner_size_modules,
            outer_padding_px=outer_padding_px,
            outer_padding_white=outer_padding_white,
        )
        layout_info = encoder.get_layout()
        cap = layout_info.data_capacity_bits // 8
    else:
        raise ValueError(f"Protocol '{protocol}' not supported, use 'basic', 'compact', or 'gray4'")
    normalized_fill_ratio = max(0.05, min(1.0, float(chunk_fill_ratio)))
    robust_cap = min(int(cap), max(64, int(cap * normalized_fill_ratio)))
    effective_chunk_size = int(robust_cap)
    requested_chunk_size = None if chunk_size is None else int(chunk_size)
    if requested_chunk_size is not None and requested_chunk_size > 0:
        if requested_chunk_size < effective_chunk_size:
            effective_chunk_size = requested_chunk_size
        elif requested_chunk_size > effective_chunk_size:
            print(
                "{0} chunk-size cap applied: requested={1} frame_capacity={2} fill_ratio={3:.2f} effective_cap={4}".format(
                    protocol,
                    requested_chunk_size,
                    cap,
                    normalized_fill_ratio,
                    effective_chunk_size,
                )
            )

    if effective_chunk_size > cap:
        raise RuntimeError(
            "chunk-size {0} exceeds frame payload capacity {1} at {2}x{3}/block={4}".format(
                effective_chunk_size, cap, width, height, block_size
            )
        )

    built = _build_chunks(
        input_path=input_path,
        compress=compress,
        chunk_size=effective_chunk_size,
        session_id=session_id,
    )
    control_items = list(built["control_items"])
    control_items.append(
        ControlPlaneItem(
            kind=CONTROL_KIND_SESSION,
            payload=_build_session_control_payload(
                session_id=session_id,
                manifest=built["manifest"],
                protocol=protocol,
                window_name=window_name,
            ),
            wire_chunk_id=CONTROL_WIRE_CHUNK_IDS[CONTROL_KIND_SESSION],
        )
    )
    payload_chunks = list(built["payload_chunks"])
    control_items.append(
        ControlPlaneItem(
            kind=CONTROL_KIND_LAYOUT,
            payload=_build_layout_control_payload(
                protocol=protocol,
                layout_info=layout_info,
                ecc_level=ecc_level,
                frame_payload_cap=cap,
                effective_chunk_size=effective_chunk_size,
                module_grid=module_grid,
            ),
            wire_chunk_id=CONTROL_WIRE_CHUNK_IDS[CONTROL_KIND_LAYOUT],
        )
    )
    control_burst_repeat = schedule.normalized_control_burst_repeat()
    sync_frames = schedule.normalized_sync_frames()
    data_realizations = schedule.normalized_data_realizations()
    payload_frame_count = len(payload_chunks) * data_realizations
    total_data_frames = ((len(control_items) + 1) * control_burst_repeat) + payload_frame_count

    # Yield metadata first so caller can access session_id, manifest, etc.
    metadata = {
        "session_id": session_id,
        "manifest": built["manifest"],
        "control_plane": [item.to_metadata() for item in control_items]
        + [
            {
                "kind": CONTROL_KIND_GENERATION,
                "family": CONTROL_FAMILY_GENERATION,
                "wire_chunk_id": CONTROL_WIRE_CHUNK_IDS[CONTROL_KIND_GENERATION],
                "payload_size": len(
                    _build_generation_control_payload(
                        generation_id=0,
                        total_frames=total_data_frames,
                        payload_chunk_count=len(payload_chunks),
                        effective_chunk_size=effective_chunk_size,
                        protocol=protocol,
                    )
                ),
            }
        ],
        "payload": built["payload"],
        "payload_chunks": payload_chunks,
        "payload_chunk_count": len(payload_chunks),
        "payload_frame_count": payload_frame_count,
        "frame_payload_cap": cap,
        "total_data_frames": total_data_frames,
        "width": width,
        "height": height,
        "block_size": block_size,
        "chunk_size": effective_chunk_size,
        "effective_chunk_size": effective_chunk_size,
        "protocol_version": version,
        "quiet_zone_px": quiet_zone_px,
        "schedule": asdict(schedule),
    }

    for i in range(sync_frames):
        header = FrameHeaderBasic.make(
            frame_type=FRAME_SYNC,
            session_id=session_id,
            epoch_id=0,
            frame_id=i,
            total_frames=total_data_frames,
            chunk_id=0,
            payload=b"",
        )
        yield {
            "kind": "sync",
            "epoch": 0,
            "frame_id": i,
            "chunk_id": 0,
            "metadata": metadata,
            "image": encoder.encode_frame(
                header,
                b"",
                width=width,
                height=height,
            ),
        }

    def _yield_epoch(epoch: int):
        frame_id = 0
        for control_item in control_items:
            for _ in range(control_burst_repeat):
                header = FrameHeaderBasic.make(
                    frame_type=FRAME_DATA,
                    session_id=session_id,
                    epoch_id=epoch,
                    frame_id=frame_id,
                    total_frames=total_data_frames,
                    chunk_id=control_item.wire_chunk_id,
                    payload=control_item.payload,
                )
                yield {
                    "kind": "data",
                    "plane": "control",
                    "control_family": CONTROL_FAMILY_BOOTSTRAP,
                    "control_kind": control_item.kind,
                    "epoch": epoch,
                    "frame_id": frame_id,
                    "chunk_id": control_item.wire_chunk_id,
                    "metadata": metadata,
                    "image": encoder.encode_frame(
                        header,
                        control_item.payload,
                        width=width,
                        height=height,
                    ),
                }
                frame_id += 1

        generation_item = ControlPlaneItem(
            kind=CONTROL_KIND_GENERATION,
            payload=_build_generation_control_payload(
                generation_id=epoch,
                total_frames=total_data_frames,
                payload_chunk_count=len(payload_chunks),
                effective_chunk_size=effective_chunk_size,
                protocol=protocol,
            ),
            wire_chunk_id=CONTROL_WIRE_CHUNK_IDS[CONTROL_KIND_GENERATION],
        )
        for _ in range(control_burst_repeat):
            header = FrameHeaderBasic.make(
                frame_type=FRAME_DATA,
                session_id=session_id,
                epoch_id=epoch,
                frame_id=frame_id,
                total_frames=total_data_frames,
                chunk_id=generation_item.wire_chunk_id,
                payload=generation_item.payload,
            )
            yield {
                "kind": "data",
                "plane": "control",
                "control_family": CONTROL_FAMILY_GENERATION,
                "control_kind": generation_item.kind,
                "epoch": epoch,
                "frame_id": frame_id,
                "chunk_id": generation_item.wire_chunk_id,
                "metadata": metadata,
                "image": encoder.encode_frame(
                    header,
                    generation_item.payload,
                    width=width,
                    height=height,
                ),
            }
            frame_id += 1

        for chunk_id, chunk in enumerate(payload_chunks, start=1):
            for realization_index in range(data_realizations):
                header = FrameHeaderBasic.make(
                    frame_type=FRAME_DATA,
                    session_id=session_id,
                    epoch_id=epoch,
                    frame_id=frame_id,
                    total_frames=total_data_frames,
                    chunk_id=chunk_id,
                    payload=chunk,
                )
                yield {
                    "kind": "data",
                    "plane": "data",
                    "control_family": None,
                    "control_kind": None,
                    "epoch": epoch,
                    "frame_id": frame_id,
                    "chunk_id": chunk_id,
                    "realization_index": realization_index,
                    "realization_count": data_realizations,
                    "metadata": metadata,
                    "image": encoder.encode_frame(
                        header,
                        chunk,
                        width=width,
                        height=height,
                    ),
                }
                frame_id += 1

        end_header = FrameHeaderBasic.make(
            frame_type=FRAME_END,
            session_id=session_id,
            epoch_id=epoch,
            frame_id=frame_id,
            total_frames=total_data_frames,
            chunk_id=0,
            payload=b"",
        )
        yield {
            "kind": "end",
            "plane": "control",
            "control_family": "control",
            "control_kind": "end",
            "epoch": epoch,
            "frame_id": frame_id,
            "chunk_id": 0,
            "metadata": metadata,
            "image": encoder.encode_frame(
                end_header,
                b"",
                width=width,
                height=height,
            ),
        }

    epochs = int(epochs)
    if epochs <= 0:
        epoch = 0
        while True:
            yield from _yield_epoch(epoch)
            epoch += 1
    else:
        for epoch in range(epochs):
            yield from _yield_epoch(epoch)


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

    # Payload-only theoretical throughput, in KiB/s.
    theoretical_payload_kibps = float(effective_chunk_size * max(1, fps)) / 1024.0
    print(
        "protocol={0} session_id={1} payload_size={2} total_chunks={3} frame_payload_cap={4} theoretical_payload_KiBps={5:.2f}".format(
            protocol,
            session_id,
            len(payload),
            len(payload_chunks),
            frame_payload_cap,
            theoretical_payload_kibps,
        )
    )

    if dump_frames:
        _mkdir(dump_frames)

    renderer = CV2Renderer(window_name=window_name, fps=fps, show_overlay=overlay)

    started = time.time()
    sent_frames = 0
    sent_data_frames = 0
    last_stats_ts = started
    last_stats_sent_frames = 0
    last_stats_sent_data_frames = 0
    next_stats_ts = started + max(0.1, float(stats_interval))
    stopped_by_user = False

    def _control_summary() -> str:
        return ",".join(
            "{0}/{1}".format(
                str(item.get("family", "control")),
                str(item.get("kind", "unknown")),
            )
            for item in control_plane_meta
        )

    def _maybe_print_sender_stats(now: float) -> None:
        nonlocal last_stats_ts, last_stats_sent_frames, last_stats_sent_data_frames, next_stats_ts
        if now < next_stats_ts:
            return
        elapsed = max(1e-6, now - last_stats_ts)
        delta_sent_frames = max(0, sent_frames - last_stats_sent_frames)
        delta_sent_data_frames = max(0, sent_data_frames - last_stats_sent_data_frames)
        tx_fps = float(delta_sent_frames) / elapsed
        data_fps = float(delta_sent_data_frames) / elapsed
        tx_payload_kibps = (float(delta_sent_data_frames * effective_chunk_size) / elapsed) / 1024.0
        print(
            "sender realtime: sent={0} data={1} tx_fps={2:.2f} data_fps={3:.2f} tx_payload_KiBps={4:.2f} control=[{5}] realizations={6}".format(
                sent_frames,
                sent_data_frames,
                tx_fps,
                data_fps,
                tx_payload_kibps,
                _control_summary(),
                data_realizations,
            )
        )
        last_stats_ts = now
        last_stats_sent_frames = sent_frames
        last_stats_sent_data_frames = sent_data_frames
        next_stats_ts = now + max(0.1, float(stats_interval))

    def _frame_name(item: Dict[str, Any]) -> str:
        if item["kind"] == "sync":
            return "sync_{0:06d}.png".format(int(item["frame_id"]))
        if item["kind"] == "data":
            if item.get("plane") == "control":
                return "epoch_{0:06d}_{1}_{2}_{3:06d}.png".format(
                    int(item["epoch"]),
                    str(item.get("control_family") or "control"),
                    str(item.get("control_kind") or "control"),
                    int(item["frame_id"]),
                )
            suffix = ""
            realization_count = int(item.get("realization_count", 1) or 1)
            if realization_count > 1:
                suffix = "_r{0:02d}of{1:02d}".format(
                    int(item.get("realization_index", 0)) + 1,
                    realization_count,
                )
            return "epoch_{0:06d}_frame_{1:06d}{2}.png".format(
                int(item["epoch"]),
                int(item["frame_id"]),
                suffix,
            )
        return "epoch_{0:06d}_end.png".format(int(item["epoch"]))

    def _overlay_for_item(item: Dict[str, Any], paused: bool) -> str:
        if item["kind"] == "sync":
            base = "SYNC {0}/{1}".format(int(item["frame_id"]) + 1, sync_frames)
        elif item["kind"] == "end":
            base = "END epoch={0}".format(int(item["epoch"]))
        else:
            base = "session={0} epoch={1} frame={2}/{3} bytes_per_frame={4}".format(
                session_id,
                int(item["epoch"]),
                int(item["frame_id"]) + 1,
                total_data_frames,
                effective_chunk_size,
            )
            if item.get("plane") == "control":
                base += " control={0}/{1} control_burst={2}".format(
                    str(item.get("control_family") or "control"),
                    str(item.get("control_kind") or "control"),
                    control_burst_repeat,
                )
            elif control_plane_meta:
                base += " control_schema={0}".format(_control_summary())
            if item.get("plane") == "data" and data_realizations > 1:
                base += " realization={0}/{1}".format(
                    int(item.get("realization_index", 0)) + 1,
                    int(item.get("realization_count", data_realizations)),
                )
        if paused:
            return base + " | SPACE start/pause | R reset | Q quit"
        return base + " | SPACE pause | R reset | Q quit"

    def _record_item(item: Dict[str, Any]) -> None:
        nonlocal sent_frames, sent_data_frames
        sent_frames += 1
        if item["kind"] == "data":
            sent_data_frames += 1
        _maybe_print_sender_stats(time.time())

    def _update_window_title(paused: bool) -> None:
        if paused:
            renderer.set_window_title("SPACE start | R reset | Q quit")
        else:
            renderer.set_window_title("SPACE pause | R reset | Q quit")

    try:
        current_item = first_frame
        last_dump_name = None  # type: Optional[str]
        paused = True
        _update_window_title(paused=True)
        while not stopped_by_user:
            if dump_frames:
                dump_name = _frame_name(current_item)
                if dump_name != last_dump_name:
                    renderer.cv2.imwrite(
                        os.path.join(dump_frames, dump_name), current_item["image"]
                    )
                    last_dump_name = dump_name
            command = renderer.show(
                current_item["image"],
                overlay_text=_overlay_for_item(current_item, paused=paused),
                pace=not paused,
            )
            if command == "quit":
                stopped_by_user = True
                break
            if command == "reset":
                frame_generator, first_frame = _build_sender_stream()
                current_item = first_frame
                paused = True
                last_dump_name = None
                renderer.reset_clock()
                _update_window_title(paused=True)
                print("sender reset: replaying from first sync frame")
                continue
            if command == "toggle_pause":
                paused = not paused
                renderer.reset_clock()
                _update_window_title(paused=paused)
                if paused:
                    print("sender paused")
                else:
                    print("sender started")
                continue
            if paused:
                continue

            _record_item(current_item)
            try:
                current_item = next(frame_generator)
            except StopIteration:
                frame_generator, first_frame = _build_sender_stream()
                current_item = first_frame
                last_dump_name = None
                renderer.reset_clock()

        elapsed = max(0.001, time.time() - started)
        observed_payload_kibps = float(sent_data_frames * effective_chunk_size) / elapsed / 1024.0
        print(
            "sender finished: sent_frames={0} sent_data_frames={1} observed_payload_KiBps={2:.2f}".format(
                sent_frames,
                sent_data_frames,
                observed_payload_kibps,
            )
        )

        if report_json:
            sender_generation = next(
                (
                    item
                    for item in control_plane_meta
                    if item.get("family") == CONTROL_FAMILY_GENERATION
                ),
                None,
            )
            sender_layout = next(
                (item for item in control_plane_meta if item.get("kind") == CONTROL_KIND_LAYOUT),
                None,
            )
            sender_session = next(
                (item for item in control_plane_meta if item.get("kind") == CONTROL_KIND_SESSION),
                None,
            )
            report = {
                "session_id": session_id,
                "protocol": protocol,
                "sent_frames": sent_frames,
                "sent_data_frames": sent_data_frames,
                "elapsed_s": elapsed,
                "bytes_per_frame": effective_chunk_size,
                "payload_chunk_count": payload_chunk_count,
                "payload_frame_count": payload_frame_count,
                "data_realizations": data_realizations,
                "theoretical_payload_kibps": theoretical_payload_kibps,
                "observed_payload_kibps": observed_payload_kibps,
                # Backward compatibility aliases (deprecated).
                "theoretical_goodput_kbps": theoretical_payload_kibps,
                "observed_kbps": observed_payload_kibps,
                "stopped_by_user": stopped_by_user,
                "control_plane": control_plane_meta,
                "control_plane_kinds": sorted(
                    str(item.get("kind", "unknown")) for item in control_plane_meta
                ),
                "control_schema": _control_summary(),
                "control_session": sender_session,
                "control_layout": sender_layout,
                "control_generation": sender_generation,
            }
            with open(report_json, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)

        return 0
    finally:
        renderer.close()
