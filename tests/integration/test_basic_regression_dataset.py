import json
from pathlib import Path

import cv2
import pytest

from screen_airdrop.receiver.decoder_basic import decode_frame_basic


@pytest.mark.real_data
def test_v31_regression_dataset_all_frames_decodable():
    repo_root = Path(__file__).resolve().parents[2]
    spec_path = repo_root / "tests" / "fixtures" / "v31_regression_cases.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    default = spec.get("default", {})

    failures = []
    for case in spec.get("cases", []):
        case_id = str(case["id"])
        frame_path = repo_root / str(case["frame_path"])
        if not frame_path.exists():
            failures.append((case_id, "missing frame", str(frame_path)))
            continue

        img = cv2.imread(str(frame_path))
        if img is None:
            failures.append((case_id, "imread failed", str(frame_path)))
            continue

        gw = int(case.get("grid_w", default.get("grid_w", 160)))
        gh = int(case.get("grid_h", default.get("grid_h", 96)))
        locator_engine = str(case.get("locator_engine", default.get("locator_engine", "new")))

        try:
            header, payload, _meta = decode_frame_basic(
                frame=img,
                detect_mode="full",
                grid_w=gw,
                grid_h=gh,
                locator_engine=locator_engine,
            )
            if len(payload) < 0 or int(header.frame_id) < 0:
                failures.append((case_id, "decoded invalid header/payload", ""))
        except Exception as exc:  # noqa: PERF203
            failures.append((case_id, "decode failed", str(exc)))

    if failures:
        lines = ["Basic regression dataset decode failures:"]
        for cid, reason, detail in failures:
            lines.append(f"- {cid}: {reason} | {detail}")
        raise AssertionError("\n".join(lines))
