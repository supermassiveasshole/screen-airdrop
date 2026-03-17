from __future__ import annotations

from pathlib import Path


def create_payload_tree(root: Path, *, name: str = "src") -> Path:
    src = root / name
    src.mkdir()
    (src / "a.txt").write_text("hello loopback", encoding="utf-8")
    (src / "b.bin").write_bytes(b"\x01\x02\x03" * 128)
    return src
