#!/usr/bin/env python3
"""Compare decoded chunk coverage between sender dumps and captured replay frames."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from screen_airdrop.receiver.frame_replay_source import FrameReplaySource
from screen_airdrop.receiver.protocol_adapter_basic import BasicProtocolDecoder
from screen_airdrop.receiver.protocol_adapter_compact import CompactProtocolDecoder
from screen_airdrop.receiver.protocol_adapter_gray4 import Gray4ProtocolDecoder


def _build_decoder(protocol: str, grid_w: int, grid_h: int):
    if protocol == "basic":
        return BasicProtocolDecoder(grid_w=grid_w, grid_h=grid_h)
    if protocol == "compact":
        return CompactProtocolDecoder(grid_w=grid_w, grid_h=grid_h)
    if protocol == "gray4":
        return Gray4ProtocolDecoder(grid_w=grid_w, grid_h=grid_h)
    raise ValueError("unsupported protocol: {0}".format(protocol))


def _iter_frame_paths(frames_dir: Path) -> list[Path]:
    files = [p for p in frames_dir.iterdir() if p.suffix.lower() in (".png", ".npy")]
    return sorted(files, key=lambda path: FrameReplaySource._sort_key(path.name))


def _load_frame(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".npy":
        return np.load(path)
    import cv2  # pylint: disable=import-outside-toplevel

    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError("failed to read frame: {0}".format(path))
    return frame


def _decode_dir(frames_dir: Path, protocol: str, grid_w: int, grid_h: int) -> list[dict[str, Any]]:
    decoder = _build_decoder(protocol, grid_w, grid_h)
    records: list[dict[str, Any]] = []
    for path in _iter_frame_paths(frames_dir):
        record: dict[str, Any] = {"file": path.name}
        try:
            decoded = decoder.decode_frame(_load_frame(path), detect_mode="full")
            header = decoded.frame_header
            record.update(
                {
                    "ok": True,
                    "chunk_id": int(header.chunk_id),
                    "frame_id": int(header.frame_id),
                    "frame_type": int(header.frame_type),
                    "payload_len": int(len(decoded.payload)),
                }
            )
        except Exception as exc:  # noqa: BLE001
            record.update({"ok": False, "error": str(exc)})
        records.append(record)
    return records


def _chunk_to_files(records: list[dict[str, Any]]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for record in records:
        if not record.get("ok"):
            continue
        chunk_id = int(record["chunk_id"])
        out.setdefault(chunk_id, []).append(str(record["file"]))
    return out


def _chunk_to_records(records: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        if not record.get("ok"):
            continue
        chunk_id = int(record["chunk_id"])
        out.setdefault(chunk_id, []).append(record)
    return out


def _parse_missing_chunks(args: argparse.Namespace) -> list[int]:
    if args.missing_chunks:
        return [int(part) for part in args.missing_chunks.split(",") if part.strip()]
    if args.report_json:
        report = json.loads(Path(args.report_json).read_text(encoding="utf-8"))
        raw = report.get("missing_chunk_ids", [])
        if isinstance(raw, list):
            return [int(item) for item in raw]
    return []


def compare_dirs(
    *,
    sender_dir: Path,
    captured_dir: Path,
    protocol: str,
    grid_w: int,
    grid_h: int,
    missing_chunks: list[int],
    neighbor_window: int,
) -> dict[str, Any]:
    sender_records = _decode_dir(sender_dir, protocol, grid_w, grid_h)
    captured_records = _decode_dir(captured_dir, protocol, grid_w, grid_h)
    sender_chunk_files = _chunk_to_files(sender_records)
    captured_chunk_files = _chunk_to_files(captured_records)
    sender_chunk_records = _chunk_to_records(sender_records)
    captured_chunk_records = _chunk_to_records(captured_records)
    sender_chunks = sorted(sender_chunk_files.keys())
    captured_chunks = sorted(captured_chunk_files.keys())
    captured_only_missing = [
        chunk_id for chunk_id in missing_chunks if chunk_id not in captured_chunk_files
    ]
    neighbor_chunks: dict[str, dict[str, Any]] = {}
    for chunk_id in missing_chunks:
        local: dict[str, Any] = {}
        for neighbor in range(chunk_id - neighbor_window, chunk_id + neighbor_window + 1):
            if neighbor <= 0:
                continue
            local[str(neighbor)] = {
                "sender_files": sender_chunk_files.get(neighbor, []),
                "captured_files": captured_chunk_files.get(neighbor, []),
                "sender_frame_ids": [
                    int(item["frame_id"]) for item in sender_chunk_records.get(neighbor, [])
                ],
                "captured_frame_ids": [
                    int(item["frame_id"]) for item in captured_chunk_records.get(neighbor, [])
                ],
            }
        neighbor_chunks[str(chunk_id)] = local
    return {
        "protocol": protocol,
        "module_grid": "{0}x{1}".format(grid_w, grid_h),
        "sender_dir": str(sender_dir),
        "captured_dir": str(captured_dir),
        "missing_chunks_requested": missing_chunks,
        "sender_total_files": len(sender_records),
        "captured_total_files": len(captured_records),
        "sender_decoded_ok": sum(1 for record in sender_records if record.get("ok")),
        "captured_decoded_ok": sum(1 for record in captured_records if record.get("ok")),
        "sender_unique_chunks": len(sender_chunks),
        "captured_unique_chunks": len(captured_chunks),
        "captured_missing_chunks": captured_only_missing,
        "neighbor_window": int(neighbor_window),
        "neighbor_chunks": neighbor_chunks,
        "missing_chunk_sender_files": {
            str(chunk_id): sender_chunk_files.get(chunk_id, []) for chunk_id in missing_chunks
        },
        "missing_chunk_captured_files": {
            str(chunk_id): captured_chunk_files.get(chunk_id, []) for chunk_id in missing_chunks
        },
        "sender_failures": [record for record in sender_records if not record.get("ok")][:32],
        "captured_failures": [record for record in captured_records if not record.get("ok")][:32],
    }


def _render_text(summary: dict[str, Any]) -> str:
    lines = [
        "Chunk Coverage Comparison",
        "protocol={0} grid={1}".format(summary["protocol"], summary["module_grid"]),
        "sender_decoded_ok={0}/{1} captured_decoded_ok={2}/{3}".format(
            int(summary["sender_decoded_ok"]),
            int(summary["sender_total_files"]),
            int(summary["captured_decoded_ok"]),
            int(summary["captured_total_files"]),
        ),
        "sender_unique_chunks={0} captured_unique_chunks={1}".format(
            int(summary["sender_unique_chunks"]),
            int(summary["captured_unique_chunks"]),
        ),
        "captured_missing_chunks={0}".format(summary["captured_missing_chunks"]),
    ]
    for chunk_id in summary["missing_chunks_requested"]:
        lines.append("")
        lines.append("chunk {0}".format(int(chunk_id)))
        lines.append(
            "  sender_files={0}".format(summary["missing_chunk_sender_files"].get(str(chunk_id), []))
        )
        lines.append(
            "  captured_files={0}".format(
                summary["missing_chunk_captured_files"].get(str(chunk_id), [])
            )
        )
        neighbors = summary.get("neighbor_chunks", {}).get(str(chunk_id), {})
        for neighbor_id, neighbor in neighbors.items():
            lines.append(
                "  neighbor {0}: sender_files={1} captured_files={2}".format(
                    neighbor_id,
                    neighbor.get("sender_files", []),
                    neighbor.get("captured_files", []),
                )
            )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare sender dump and captured replay chunks")
    parser.add_argument("--sender-dir", required=True, help="sender dump-frames directory")
    parser.add_argument("--captured-dir", required=True, help="pipeline capture-dump directory")
    parser.add_argument(
        "--protocol",
        required=True,
        choices=["basic", "compact", "gray4"],
        help="protocol to decode",
    )
    parser.add_argument("--module-grid", required=True, help="grid like 240x144")
    parser.add_argument(
        "--missing-chunks",
        default="",
        help="comma-separated missing chunk ids to inspect",
    )
    parser.add_argument(
        "--report-json",
        default=None,
        help="optional receiver report json to source missing_chunk_ids from",
    )
    parser.add_argument(
        "--neighbor-window",
        type=int,
        default=1,
        help="how many adjacent chunks to include around each missing chunk",
    )
    parser.add_argument("--output-json", default=None, help="optional output json path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    grid_w, grid_h = [int(part) for part in str(args.module_grid).lower().split("x", 1)]
    missing_chunks = _parse_missing_chunks(args)
    summary = compare_dirs(
        sender_dir=Path(args.sender_dir),
        captured_dir=Path(args.captured_dir),
        protocol=str(args.protocol),
        grid_w=grid_w,
        grid_h=grid_h,
        missing_chunks=missing_chunks,
        neighbor_window=max(0, int(args.neighbor_window)),
    )
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(_render_text(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
