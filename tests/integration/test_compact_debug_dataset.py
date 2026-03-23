from pathlib import Path

import cv2
import pytest

from screen_airdrop.common.transport.protocol_basic import FRAME_DATA
from screen_airdrop.receiver.transport.compact.decoder import decode_frame_compact


@pytest.mark.real_data
def test_compact_debug_frames_all_decodable():
    repo_root = Path(__file__).resolve().parents[2]
    frames = sorted((repo_root / "debug" / "compact").glob("frame_*.raw.png"))
    assert frames, "missing compact debug frames under debug/compact"

    failures: list[str] = []
    for frame_path in frames:
        img = cv2.imread(str(frame_path))
        if img is None:
            failures.append(f"{frame_path.name}: imread failed")
            continue

        try:
            header, payload, meta = decode_frame_compact(
                frame=img,
                detect_mode="track",
                forced_roi=(0, 0, img.shape[1], img.shape[0]),
                roi_only=True,
                manual_strict=True,
                locator_engine="auto",
            )
        except Exception as exc:  # noqa: PERF203
            failures.append(f"{frame_path.name}: decode failed | {exc}")
            continue

        if meta.locator_engine not in {"legacy", "corner"}:
            failures.append(
                f"{frame_path.name}: expected legacy/corner locator, got {meta.locator_engine}"
            )
        if int(header.frame_id) < 0 or int(header.chunk_id) < 0:
            failures.append(f"{frame_path.name}: invalid header values")
        if int(header.frame_type) == FRAME_DATA and len(payload) == 0:
            failures.append(f"{frame_path.name}: data frame decoded with empty payload")

    if failures:
        lines = ["Compact debug dataset decode failures:"]
        lines.extend(f"- {line}" for line in failures)
        raise AssertionError("\n".join(lines))


@pytest.mark.real_data
def test_compact_v4_debug_frames_all_decodable():
    repo_root = Path(__file__).resolve().parents[2]
    frames = sorted((repo_root / "debug" / "compact_v4").glob("frame_*.raw.png"))
    assert frames, "missing compact_v4 debug frames under debug/compact_v4"

    failures: list[str] = []
    for frame_path in frames:
        img = cv2.imread(str(frame_path))
        if img is None:
            failures.append(f"{frame_path.name}: imread failed")
            continue

        try:
            header, payload, meta = decode_frame_compact(
                frame=img,
                detect_mode="track",
                forced_roi=(0, 0, img.shape[1], img.shape[0]),
                roi_only=True,
                manual_strict=True,
                locator_engine="auto",
            )
        except Exception as exc:  # noqa: PERF203
            failures.append(f"{frame_path.name}: decode failed | {exc}")
            continue

        if meta.locator_engine != "corner":
            failures.append(
                f"{frame_path.name}: expected corner locator, got {meta.locator_engine}"
            )
        if int(header.frame_id) < 0 or int(header.chunk_id) < 0:
            failures.append(f"{frame_path.name}: invalid header values")
        if int(header.frame_type) == FRAME_DATA and len(payload) == 0:
            failures.append(f"{frame_path.name}: data frame decoded with empty payload")

    if failures:
        lines = ["Compact v4 debug dataset decode failures:"]
        lines.extend(f"- {line}" for line in failures)
        raise AssertionError("\n".join(lines))
