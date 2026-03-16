#!/usr/bin/env python3
"""Extract sender/captured frame windows for problematic chunks."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _copy_many(files: list[str], src_dir: Path, dst_dir: Path) -> list[str]:
    copied: list[str] = []
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in files:
        src = src_dir / name
        if not src.exists():
            continue
        dst = dst_dir / name
        shutil.copy2(src, dst)
        copied.append(name)
    return copied


def extract_windows(compare_summary: dict[str, Any], sender_dir: Path, captured_dir: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    extracted: dict[str, Any] = {
        "source_compare_json": compare_summary,
        "chunks": {},
    }
    neighbor_chunks = compare_summary.get("neighbor_chunks", {})
    missing_chunks = compare_summary.get("missing_chunks_requested", [])
    for chunk_id in missing_chunks:
        chunk_key = str(int(chunk_id))
        chunk_dir = output_dir / ("chunk_" + chunk_key)
        sender_chunk_dir = chunk_dir / "sender"
        captured_chunk_dir = chunk_dir / "captured"
        neighbors = neighbor_chunks.get(chunk_key, {})
        chunk_manifest: dict[str, Any] = {"neighbors": {}}
        for neighbor_key, payload in neighbors.items():
            neighbor_sender = list(payload.get("sender_files", []))
            neighbor_captured = list(payload.get("captured_files", []))
            sender_neighbor_dir = sender_chunk_dir / ("chunk_" + str(neighbor_key))
            captured_neighbor_dir = captured_chunk_dir / ("chunk_" + str(neighbor_key))
            copied_sender = _copy_many(neighbor_sender, sender_dir, sender_neighbor_dir)
            copied_captured = _copy_many(neighbor_captured, captured_dir, captured_neighbor_dir)
            chunk_manifest["neighbors"][str(neighbor_key)] = {
                "sender_files": copied_sender,
                "captured_files": copied_captured,
                "sender_frame_ids": list(payload.get("sender_frame_ids", [])),
                "captured_frame_ids": list(payload.get("captured_frame_ids", [])),
            }
        extracted["chunks"][chunk_key] = chunk_manifest
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(extracted, ensure_ascii=False, indent=2), encoding="utf-8")
    return extracted


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract neighboring sender/captured frames for missing chunks")
    parser.add_argument("--compare-json", required=True, help="JSON from compare_captured_chunks.py")
    parser.add_argument("--sender-dir", required=True, help="sender dump directory")
    parser.add_argument("--captured-dir", required=True, help="captured replay dump directory")
    parser.add_argument("--output-dir", required=True, help="destination directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    compare_summary = _load_json(Path(args.compare_json))
    extracted = extract_windows(
        compare_summary=compare_summary,
        sender_dir=Path(args.sender_dir),
        captured_dir=Path(args.captured_dir),
        output_dir=Path(args.output_dir),
    )
    print(
        "extracted_chunks={0} output_dir={1}".format(
            len(extracted.get("chunks", {})),
            args.output_dir,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
