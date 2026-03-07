"""Packing/compression/chunking helpers compatible with Python 3.7+."""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import tarfile
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from .errors import E1001, E1002, E1003, ScreenAirdropError
from .manifest import Manifest
from .protocol_basic import PROTOCOL_VERSION


def ensure_input_exists(path: str) -> None:
    if not os.path.exists(path):
        raise ScreenAirdropError(E1001, "input path does not exist: {0}".format(path))


def build_entries(path: str) -> List[Dict[str, object]]:
    entries = []
    root = os.path.abspath(path)

    if os.path.isfile(root):
        stat = os.lstat(root)
        entries.append(
            {
                "path": os.path.basename(root),
                "type": "file",
                "size": int(stat.st_size),
                "mode": int(stat.st_mode),
                "mtime": int(stat.st_mtime),
            }
        )
        return entries

    for current_root, dirs, files in os.walk(root):
        rel_root = os.path.relpath(current_root, root)
        rel_root = "." if rel_root == "." else rel_root.replace("\\", "/")
        root_stat = os.lstat(current_root)
        entries.append(
            {
                "path": rel_root,
                "type": "dir",
                "size": 0,
                "mode": int(root_stat.st_mode),
                "mtime": int(root_stat.st_mtime),
            }
        )
        dirs.sort()
        files.sort()
        for name in files:
            full = os.path.join(current_root, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            stat = os.lstat(full)
            entries.append(
                {
                    "path": rel,
                    "type": "file",
                    "size": int(stat.st_size),
                    "mode": int(stat.st_mode),
                    "mtime": int(stat.st_mtime),
                    "sha256": file_sha256(full),
                }
            )
    return entries


def build_tar_bytes(path: str) -> bytes:
    ensure_input_exists(path)
    try:
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as tf:
            arcname = os.path.basename(os.path.abspath(path))
            tf.add(path, arcname=arcname)
        return stream.getvalue()
    except Exception as exc:
        raise ScreenAirdropError(E1002, "tar build failed: {0}".format(exc))


def compress_bytes(data: bytes, method: str) -> bytes:
    if method == "none":
        return data
    if method == "gzip":
        try:
            return gzip.compress(data)
        except Exception as exc:
            raise ScreenAirdropError(E1003, "gzip failed: {0}".format(exc))
    raise ScreenAirdropError(E1003, "unsupported compression: {0}".format(method))


def chunk_bytes(data: bytes, chunk_size: int) -> List[bytes]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def build_manifest(
    input_path: str,
    session_id: int,
    compress_method: str,
    chunk_size: int,
    payload: bytes,
    total_chunks: int,
) -> Manifest:
    entries = build_entries(input_path)
    return Manifest(
        protocol_version=int(PROTOCOL_VERSION),
        session_id=session_id,
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        input_root_name=os.path.basename(os.path.abspath(input_path)),
        pack="tar",
        compress=compress_method,
        chunk_size=chunk_size,
        total_chunks=total_chunks,
        payload_size=len(payload),
        payload_sha256=sha256_bytes(payload),
        entries=entries,
    )


def build_payload_and_manifest(
    input_path: str,
    compress_method: str,
    chunk_size: int,
    session_id: int,
) -> Tuple[bytes, Manifest, List[bytes]]:
    tar_bytes = build_tar_bytes(input_path)
    payload = compress_bytes(tar_bytes, compress_method)
    chunks = chunk_bytes(payload, chunk_size)
    manifest = build_manifest(
        input_path=input_path,
        session_id=session_id,
        compress_method=compress_method,
        chunk_size=chunk_size,
        payload=payload,
        total_chunks=len(chunks),
    )
    return payload, manifest, chunks
