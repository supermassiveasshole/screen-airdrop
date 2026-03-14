#!/usr/bin/env python3
"""Scan decode success on small sampled payloads instead of full transfers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from benchmark_common import (
        DISPLAY_MODES,
        ProtocolConfig,
        display_dimensions,
        display_note,
        ensure_sample_payload_file,
        make_encoder,
        payload_size_for_ratio,
        protocol_config_dict,
        write_json_result,
    )
except ModuleNotFoundError:
    from bench.benchmark_common import (
        DISPLAY_MODES,
        ProtocolConfig,
        display_dimensions,
        display_note,
        ensure_sample_payload_file,
        make_encoder,
        payload_size_for_ratio,
        protocol_config_dict,
        write_json_result,
    )

try:
    from compare_end_to_end import _run_replay_case, _screen_runbook_case
except ModuleNotFoundError:
    from bench.compare_end_to_end import _run_replay_case, _screen_runbook_case

ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "frame_decode_success_status.md"
DEFAULT_COMPACT_GRIDS = "180x110,192x118,208x128,224x136,240x144"
DEFAULT_PAYLOAD_RATIOS = "0.90,0.95,0.98,1.00"
DEFAULT_DISPLAY_MODES = "fullscreen"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Frame decode success scan using sampled payloads.")
    parser.add_argument("--mode", choices=["replay", "screen", "all"], default="all")
    parser.add_argument("--ecc", choices=["Q"], default="Q")
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--capture-fps", type=int, default=30)
    parser.add_argument("--benchmark-seconds", type=int, default=15)
    parser.add_argument("--sample-chunks", type=int, default=32)
    parser.add_argument("--compact-grids", type=str, default=DEFAULT_COMPACT_GRIDS)
    parser.add_argument("--payload-ratios", type=str, default=DEFAULT_PAYLOAD_RATIOS)
    parser.add_argument("--display-modes", type=str, default=DEFAULT_DISPLAY_MODES)
    parser.add_argument("--output-json", type=str, default="")
    return parser.parse_args()


def _parse_grid_list(spec: str) -> list[tuple[int, int]]:
    grids: list[tuple[int, int]] = []
    for part in spec.split(","):
        token = part.strip().lower()
        if not token:
            continue
        w, h = token.split("x", 1)
        grids.append((int(w), int(h)))
    return grids


def _parse_ratio_list(spec: str) -> list[float]:
    ratios = [float(part.strip()) for part in spec.split(",") if part.strip()]
    for ratio in ratios:
        if ratio <= 0.0 or ratio > 1.0:
            raise ValueError(f"payload ratio must be within (0, 1], got {ratio}")
    return ratios


def _parse_display_modes(spec: str) -> list[str]:
    modes = [part.strip() for part in spec.split(",") if part.strip()]
    for mode in modes:
        if mode not in DISPLAY_MODES:
            raise ValueError(f"unsupported display mode: {mode}")
    return modes


def _candidate_cases(
    *,
    ecc_level: str,
    fps: int,
    capture_fps: int,
    benchmark_seconds: int,
    sample_chunks: int,
    compact_grids: list[tuple[int, int]],
    payload_ratios: list[float],
    display_modes: list[str],
) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = [
        {
            "protocol": "basic",
            "display_mode": "fullscreen",
            "config": ProtocolConfig("basic", 160, 96),
            "payload_ratio": 0.90,
            "sample_chunks": sample_chunks,
            "ecc_level": ecc_level,
            "fps": fps,
            "capture_fps": capture_fps,
            "benchmark_seconds": benchmark_seconds,
        }
    ]
    for display_mode in display_modes:
        for grid_w, grid_h in compact_grids:
            for payload_ratio in payload_ratios:
                cases.append(
                    {
                        "protocol": "compact",
                        "display_mode": display_mode,
                        "config": ProtocolConfig("compact", grid_w, grid_h),
                        "payload_ratio": payload_ratio,
                        "sample_chunks": sample_chunks,
                        "ecc_level": ecc_level,
                        "fps": fps,
                        "capture_fps": capture_fps,
                        "benchmark_seconds": benchmark_seconds,
                    }
                )
    return cases


def _materialize_case(case: dict[str, Any]) -> dict[str, Any]:
    config: ProtocolConfig = case["config"]
    encoder = make_encoder(config, case["ecc_level"])
    layout = encoder.get_layout()
    frame_payload_cap = int(layout.data_capacity_bits // 8)
    effective_chunk_size = payload_size_for_ratio(layout, float(case["payload_ratio"]))
    sample_bytes = int(case["sample_chunks"]) * effective_chunk_size
    frame_width, frame_height = display_dimensions(case["display_mode"])
    sample_path = ensure_sample_payload_file(
        stem="{0}_{1}_{2}_{3:.2f}".format(
            config.protocol,
            f"{config.grid_w}x{config.grid_h}",
            case["display_mode"],
            float(case["payload_ratio"]),
        ).replace(".", "p"),
        size_bytes=sample_bytes,
    )
    realized = dict(case)
    realized.update(
        {
            "module_grid": f"{config.grid_w}x{config.grid_h}",
            "frame_payload_cap": frame_payload_cap,
            "effective_chunk_size": effective_chunk_size,
            "sample_file": str(sample_path),
            "sample_bytes": sample_bytes,
            "frame_width": frame_width,
            "frame_height": frame_height,
        }
    )
    return realized


def _normalize_replay(case: dict[str, Any], replay_result: dict[str, Any]) -> dict[str, Any]:
    raw_fps = float(replay_result.get("raw_frame_rate_fps", 0.0))
    dec_fps = float(replay_result.get("valid_frame_rate_fps", 0.0))
    decode_success_rate = 0.0 if raw_fps <= 1e-6 else dec_fps / raw_fps
    return {
        "benchmark_kind": "frame_decode_success_replay",
        "protocol": case["protocol"],
        "display_mode": case["display_mode"],
        "display_note": display_note(case["display_mode"]),
        "module_grid": case["module_grid"],
        "config": protocol_config_dict(case["config"]),
        "ecc_level": case["ecc_level"],
        "payload_ratio": float(case["payload_ratio"]),
        "frame_payload_cap": int(case["frame_payload_cap"]),
        "effective_chunk_size": int(case["effective_chunk_size"]),
        "sample_chunks": int(case["sample_chunks"]),
        "sample_bytes": int(case["sample_bytes"]),
        "sample_file": case["sample_file"],
        "benchmark_seconds": int(case["benchmark_seconds"]),
        "frame_width": int(case["frame_width"]),
        "frame_height": int(case["frame_height"]),
        "cap_fps": raw_fps,
        "dec_fps": dec_fps,
        "decode_success_rate": decode_success_rate,
        "goodput_kib_per_s": float(replay_result.get("goodput_kibps", 0.0)),
        "bad_frame_rate": float(replay_result.get("bad_frame_rate", 1.0)),
        "locator_fail_rate": float(replay_result.get("locator_fail_rate", 1.0)),
        "avg_decode_ms": float(replay_result.get("avg_decode_ms", 0.0)),
        "locator_engine": str(replay_result.get("locator_engine", "")),
        "exit_code": int(replay_result.get("exit_code", 1)),
    }


def _replay_pass(result: dict[str, Any]) -> bool:
    return (
        int(result["exit_code"]) == 0
        and float(result["decode_success_rate"]) >= 0.75
        and float(result["locator_fail_rate"]) <= 0.10
        and float(result["bad_frame_rate"]) <= 0.20
    )


def _screen_runbook(case: dict[str, Any]) -> dict[str, Any]:
    runbook = _screen_runbook_case(
        config=case["config"],
        layout_mode="sampled_success",
        ecc_level=case["ecc_level"],
        payload_mode="fixed",
        payload_size=int(case["effective_chunk_size"]),
        fps=int(case["fps"]),
        capture_fps=int(case["capture_fps"]),
        benchmark_seconds=int(case["benchmark_seconds"]),
        stats_interval=1.0,
        input_path=case["sample_file"],
        frame_width=int(case["frame_width"]),
        frame_height=int(case["frame_height"]),
    )
    runbook.update(
        {
            "display_mode": case["display_mode"],
            "display_note": display_note(case["display_mode"]),
            "module_grid": case["module_grid"],
            "payload_ratio": float(case["payload_ratio"]),
            "frame_payload_cap": int(case["frame_payload_cap"]),
            "effective_chunk_size": int(case["effective_chunk_size"]),
            "sample_chunks": int(case["sample_chunks"]),
            "sample_bytes": int(case["sample_bytes"]),
            "sample_file": case["sample_file"],
        }
    )
    return runbook


def _select_candidates(results: list[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    stable = [r for r in results if r["protocol"] == "compact" and _replay_pass(r)]
    if not stable:
        return {"best_decode_success": None, "best_margin": None}
    best_decode_success = sorted(
        stable,
        key=lambda r: (
            float(r["decode_success_rate"]),
            float(r["goodput_kib_per_s"]),
            float(r["cap_fps"]),
            float(r["dec_fps"]),
            -float(r["payload_ratio"]),
        ),
        reverse=True,
    )[0]
    max_success = float(best_decode_success["decode_success_rate"])
    near_best = [r for r in stable if float(r["decode_success_rate"]) >= max_success - 0.02]
    best_margin = sorted(
        near_best,
        key=lambda r: (
            float(r["payload_ratio"]),
            -float(r["bad_frame_rate"]),
            -float(r["locator_fail_rate"]),
            -float(r["goodput_kib_per_s"]),
        ),
    )[0]
    return {"best_decode_success": best_decode_success, "best_margin": best_margin}


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Frame Decode Success Status",
        "",
        "This file is generated by `bench/scan_frame_decode_success.py`.",
        "",
        "## Scope",
        "",
        "- benchmark target: frame decode success on sampled payloads",
        "- scene: local `screen` + manual ROI",
        "- sample strategy: deterministic small binary payloads sized to roughly `sample_chunks * chunk_size`",
        "- replay is used only as a cheap filter before screen runs",
        "",
        "## Replay Results",
        "",
        "| protocol | display | grid | ratio | sample chunks | decode success | goodput KiB/s | bad | loc_fail |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in report["replay_results"]:
        lines.append(
            "| {protocol} | {display_mode} | {module_grid} | {payload_ratio:.2f} | {sample_chunks} | "
            "{decode_success_rate:.3f} | {goodput_kib_per_s:.2f} | {bad_frame_rate:.3f} | {locator_fail_rate:.3f} |".format(
                **item
            )
        )
    for label in ("best_decode_success", "best_margin"):
        item = report.get(label)
        lines.extend(["", f"## {label.replace('_', ' ').title()}", ""])
        if not item:
            lines.append("- none")
            continue
        lines.extend(
            [
                f"- display: `{item['display_mode']}`",
                f"- grid: `{item['module_grid']}`",
                f"- payload ratio: `{item['payload_ratio']:.2f}`",
                f"- decode success: `{item['decode_success_rate']:.3f}`",
                f"- goodput: `{item['goodput_kib_per_s']:.2f} KiB/s`",
            ]
        )
    lines.extend(["", "## Screen Runbook", ""])
    for item in report["screen_runbook"]:
        lines.extend(
            [
                f"### {item['protocol']} | {item['display_mode']} | {item['module_grid']} | ratio={item['payload_ratio']:.2f}",
                "",
                f"- note: {item['display_note']}",
                f"- sample file: `{item['sample_file']}`",
                f"- sample chunks target: `{item['sample_chunks']}`",
                f"- effective chunk size: `{item['effective_chunk_size']} B`",
                "",
                "Sender:",
                "```bash",
                item["sender_command"],
                "```",
                "",
                "Receiver:",
                "```bash",
                item["receiver_command"],
                "```",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    cases = _candidate_cases(
        ecc_level=args.ecc,
        fps=args.fps,
        capture_fps=args.capture_fps,
        benchmark_seconds=args.benchmark_seconds,
        sample_chunks=args.sample_chunks,
        compact_grids=_parse_grid_list(args.compact_grids),
        payload_ratios=_parse_ratio_list(args.payload_ratios),
        display_modes=_parse_display_modes(args.display_modes),
    )
    materialized = [_materialize_case(case) for case in cases]

    replay_results: list[dict[str, Any]] = []
    if args.mode in ("replay", "all"):
        for case in materialized:
            replay = _run_replay_case(
                config=case["config"],
                layout_mode="sampled_success",
                ecc_level=case["ecc_level"],
                payload_mode="fixed",
                payload_size=int(case["effective_chunk_size"]),
                fps=int(case["fps"]),
                benchmark_seconds=int(case["benchmark_seconds"]),
                stats_interval=1.0,
                input_path=case["sample_file"],
                frame_width=int(case["frame_width"]),
                frame_height=int(case["frame_height"]),
            )
            replay_results.append(_normalize_replay(case, replay))

    passed = materialized
    if replay_results:
        keys = {
            (item["protocol"], item["display_mode"], item["module_grid"], round(item["payload_ratio"], 4))
            for item in replay_results
            if _replay_pass(item)
        }
        passed = [
            case
            for case in materialized
            if (case["protocol"], case["display_mode"], case["module_grid"], round(float(case["payload_ratio"]), 4))
            in keys
        ]

    screen_runbook = []
    if args.mode in ("screen", "all"):
        screen_runbook = [_screen_runbook(case) for case in passed]

    selection = _select_candidates(replay_results)
    report = {
        "benchmark_kind": "frame_decode_success_scan",
        "assumptions": {
            "scene": "local_screen_manual_roi",
            "ecc_level": args.ecc,
            "sample_chunks": args.sample_chunks,
            "replay_prefilter_only": True,
        },
        "replay_results": replay_results,
        "screen_runbook": screen_runbook,
        "best_decode_success": selection["best_decode_success"],
        "best_margin": selection["best_margin"],
    }
    out_path = write_json_result("frame_decode_success_scan", report)
    DOC_PATH.write_text(_render_markdown(report), encoding="utf-8")
    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"saved_json": str(out_path), "saved_markdown": str(DOC_PATH)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
