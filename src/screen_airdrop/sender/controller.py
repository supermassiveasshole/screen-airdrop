"""Sender controller: package input, encode chunks, and broadcast frames in epochs."""

from __future__ import annotations

import json
import os
import random
import time
from typing import Any, Dict, Generator, Optional

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
from screen_airdrop.sender.renderer_cv2 import CV2Renderer

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
    chunks = [manifest_bytes] + payload_chunks
    return {
        "payload": payload,
        "manifest": manifest,
        "payload_chunks": payload_chunks,
        "chunks": chunks,
    }


def build_encoded_frames(
    input_path: str,
    block_size: int = 6,
    chunk_size: int = 2048,
    compress: str = "gzip",
    sync_frames: int = 30,
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
) -> Generator[Dict[str, Any], None, None]:
    if session_id is None:
        session_id = random.getrandbits(64)
    outer_padding_white = outer_padding_color.lower() == "white"

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
    else:
        raise ValueError(f"Protocol '{protocol}' not supported, use 'basic' or 'compact'")
    effective_chunk_size = int(chunk_size)
    if protocol in ("basic", "compact"):
        robust_cap = min(int(cap), max(64, int(cap * 0.9)))
        if effective_chunk_size > robust_cap:
            effective_chunk_size = robust_cap
            print(
                "{0} robust chunk-size cap applied: requested={1} frame_capacity={2} robust_cap={3}".format(
                    protocol,
                    chunk_size,
                    cap,
                    effective_chunk_size,
                )
            )

    if effective_chunk_size > cap:
        raise RuntimeError(
            "chunk-size {0} exceeds frame payload capacity {1} at {2}x{3}/block={4}".format(
                chunk_size, cap, width, height, block_size
            )
        )

    built = _build_chunks(
        input_path=input_path,
        compress=compress,
        chunk_size=effective_chunk_size,
        session_id=session_id,
    )
    chunks = list(built["chunks"])
    payload_chunks = list(built["payload_chunks"])
    manifest_repeat = max(1, int(manifest_repeat))
    total_data_frames = manifest_repeat + len(payload_chunks)

    # Yield metadata first so caller can access session_id, manifest, etc.
    metadata = {
        "session_id": session_id,
        "manifest": built["manifest"],
        "payload": built["payload"],
        "payload_chunks": payload_chunks,
        "frame_payload_cap": cap,
        "total_data_frames": total_data_frames,
        "width": width,
        "height": height,
        "block_size": block_size,
        "chunk_size": chunk_size,
        "effective_chunk_size": effective_chunk_size,
        "protocol_version": version,
        "quiet_zone_px": quiet_zone_px,
    }

    for i in range(max(0, sync_frames)):
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
        manifest_chunk = chunks[0]
        for _ in range(manifest_repeat):
            header = FrameHeaderBasic.make(
                frame_type=FRAME_DATA,
                session_id=session_id,
                epoch_id=epoch,
                frame_id=frame_id,
                total_frames=total_data_frames,
                chunk_id=0,
                payload=manifest_chunk,
            )
            yield {
                "kind": "data",
                "epoch": epoch,
                "frame_id": frame_id,
                "chunk_id": 0,
                "metadata": metadata,
                "image": encoder.encode_frame(
                    header,
                    manifest_chunk,
                    width=width,
                    height=height,
                ),
            }
            frame_id += 1

        for chunk_id, chunk in enumerate(payload_chunks, start=1):
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
                "epoch": epoch,
                "frame_id": frame_id,
                "chunk_id": chunk_id,
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
    chunk_size: int = 2048,
    fps: int = 12,
    compress: str = "gzip",
    sync_frames: int = 30,
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
) -> int:
    if outer_padding_color.lower() not in ("black", "white"):
        raise RuntimeError("invalid outer-padding-color: {0}".format(outer_padding_color))
    session_id = random.getrandbits(64)

    def _build_sender_stream():
        stream = build_encoded_frames(
            input_path=input_path,
            block_size=block_size,
            chunk_size=chunk_size,
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
            "sender realtime: sent={0} data={1} tx_fps={2:.2f} data_fps={3:.2f} tx_payload_KiBps={4:.2f}".format(
                sent_frames,
                sent_data_frames,
                tx_fps,
                data_fps,
                tx_payload_kibps,
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
            return "epoch_{0:06d}_frame_{1:06d}.png".format(
                int(item["epoch"]),
                int(item["frame_id"]),
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
            report = {
                "session_id": session_id,
                "protocol": protocol,
                "sent_frames": sent_frames,
                "sent_data_frames": sent_data_frames,
                "elapsed_s": elapsed,
                "bytes_per_frame": effective_chunk_size,
                "theoretical_payload_kibps": theoretical_payload_kibps,
                "observed_payload_kibps": observed_payload_kibps,
                # Backward compatibility aliases (deprecated).
                "theoretical_goodput_kbps": theoretical_payload_kibps,
                "observed_kbps": observed_payload_kibps,
                "stopped_by_user": stopped_by_user,
            }
            with open(report_json, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)

        return 0
    finally:
        renderer.close()
