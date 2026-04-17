#!/usr/bin/env python3
"""End-to-end benchmark entrypoint.

Replay mode is fully automated.
Screen mode is semi-automated: it emits a runbook with strict commands.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from screen_airdrop.common.information import CodingScheme, expand_equation_terms

try:
    from benchmark_common import (
        ECC_LEVELS,
        LAYOUT_MODES,
        PAYLOAD_MODES,
        ProtocolConfig,
        make_encoder,
        payload_size_for_mode,
        protocol_config_dict,
        protocol_configs,
        write_json_result,
    )
except ModuleNotFoundError:
    from bench.benchmark_common import (
        ECC_LEVELS,
        LAYOUT_MODES,
        PAYLOAD_MODES,
        ProtocolConfig,
        make_encoder,
        payload_size_for_mode,
        protocol_config_dict,
        protocol_configs,
        write_json_result,
    )

from screen_airdrop.receiver.cli import main as receiver_main
from screen_airdrop.sender.application.controller import build_encoded_frames

ROOT = Path(__file__).resolve().parents[1]
FORMAL_CODED_DEGREES = (2, 3, 4)
FORMAL_CODED_REDUNDANCIES = (1, 2, 4)
FORMAL_LOSS_PROFILES = ("drop1_g0", "drop2_g0", "drop3_g0")
FORMAL_K_VALUES = (4, 6, 8)
FORMAL_CODED_SCHEMES = (
    CodingScheme.GF256_SEED_V1,
    CodingScheme.GF256_SEED_V2,
)
REPRESENTATIVE_DOUBLE_LOSS_BY_K = {
    4: ((1, 2), (1, 4), (2, 3)),
    6: ((1, 2), (1, 6), (3, 4)),
    8: ((1, 2), (1, 8), (4, 5)),
}
REPRESENTATIVE_TRIPLE_LOSS_BY_K = {
    4: ((1, 2, 3),),
    6: ((1, 2, 3), (1, 3, 6)),
    8: ((1, 2, 3), (1, 4, 8)),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="End-to-end benchmark for basic vs compact.")
    parser.add_argument("--mode", choices=["replay", "screen"], default="screen")
    parser.add_argument(
        "--protocol",
        choices=["basic", "compact", "gray4", "layered", "all"],
        default="layered",
    )
    parser.add_argument("--layout-mode", choices=list(LAYOUT_MODES), default="same_grid")
    parser.add_argument("--ecc", choices=["all", *ECC_LEVELS], default="L")
    parser.add_argument("--payload-mode", choices=list(PAYLOAD_MODES), default="fixed")
    parser.add_argument("--payload-size", type=int, default=500)
    parser.add_argument("--compress", choices=["gzip", "none"], default="none")
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--module-grid", type=str, default="224x136")
    parser.add_argument("--capture-fps", type=int, default=30)
    parser.add_argument("--stats-interval", type=float, default=1.0)
    parser.add_argument("--benchmark-seconds", type=int, default=30)
    parser.add_argument(
        "--benchmark-goal",
        choices=["throughput_completion", "recovery_upper_bound"],
        default="throughput_completion",
    )
    parser.add_argument("--max-idle-seconds", type=int, default=3)
    parser.add_argument("--runtime-guard-seconds", type=int, default=0)
    parser.add_argument(
        "--decode-workers",
        type=int,
        default=max(1, min(4, int(os.cpu_count() or 1))),
    )
    parser.add_argument(
        "--replay-geometry-mode",
        choices=["stateful", "stateless"],
        default="stateless",
    )
    parser.add_argument(
        "--source-mode",
        choices=["simulated_live", "replay"],
        default="simulated_live",
    )
    parser.add_argument(
        "--simulated-live-pacing",
        choices=["none", "sender_fps"],
        default="none",
    )
    parser.add_argument("--systematic-generation-size", type=int, default=6)
    parser.add_argument(
        "--input",
        type=str,
        default=str(ROOT / "tests" / "fixtures" / "real_data" / "regular_pdf"),
    )
    parser.add_argument("--output-json", type=str, default="")
    parser.add_argument("--emit-coded-units", action="store_true")
    parser.add_argument("--coded-redundancy-count", type=int, default=0)
    parser.add_argument("--coded-degree", type=int, default=2)
    parser.add_argument(
        "--coded-scheme",
        choices=[scheme.value for scheme in FORMAL_CODED_SCHEMES],
        default=CodingScheme.GF256_SEED_V2.value,
    )
    parser.add_argument(
        "--compare-coded-schemes",
        action="store_true",
        help="run coded benchmark cases for both gf256_seed_v1 and gf256_seed_v2",
    )
    parser.add_argument(
        "--coded-matrix",
        action="store_true",
        help="run the formal GF(2^8) robustness matrix (systematic baseline plus degree 2/3/4 and redundancy 1/2/4)",
    )
    parser.add_argument(
        "--lossy-coded-matrix",
        action="store_true",
        help="run the loss-injected GF(2^8) robustness matrix using fixed systematic drop profiles on generation 0",
    )
    parser.add_argument(
        "--family-quality-matrix",
        action="store_true",
        help="run the V1/V2 family-quality matrix across K=4/6/8 with representative loss profiles",
    )
    parser.add_argument("--matrix-k-values", type=str, default="4,6,8")
    parser.add_argument(
        "--matrix-loss-mode",
        choices=["representative"],
        default="representative",
    )
    parser.add_argument("--include-coded-loss", action="store_true", default=True)
    parser.add_argument("--no-coded-loss", action="store_false", dest="include_coded_loss")
    parser.add_argument("--summary-json", type=str, default="")
    return parser.parse_args()


def _coded_matrix_cases(
    *,
    enabled: bool,
    coded_schemes: Sequence[CodingScheme] | None = None,
) -> list[dict[str, int | bool | str]]:
    scheme_list = list(coded_schemes or [CodingScheme.GF256_SEED_V2])
    if not enabled:
        return [
            {
                "emit_coded_units": False,
                "coded_redundancy_count": 0,
                "coded_degree": 0,
                "coded_scheme": "",
                "matrix_label": "systematic_only",
            }
        ]
    cases = [
        {
            "emit_coded_units": False,
            "coded_redundancy_count": 0,
            "coded_degree": 0,
            "coded_scheme": "",
            "matrix_label": "systematic_only",
        }
    ]
    for scheme in scheme_list:
        for redundancy in FORMAL_CODED_REDUNDANCIES:
            for degree in FORMAL_CODED_DEGREES:
                cases.append(
                    {
                        "emit_coded_units": True,
                        "coded_redundancy_count": int(redundancy),
                        "coded_degree": int(degree),
                        "coded_scheme": scheme.value,
                        "matrix_label": f"{scheme.value}_r{int(redundancy)}_d{int(degree)}",
                    }
                )
    return cases


def _loss_profiles(*, enabled: bool) -> list[str]:
    if not enabled:
        return [""]
    return list(FORMAL_LOSS_PROFILES)


def _parse_matrix_k_values(raw_value: str) -> list[int]:
    values = [int(part.strip()) for part in str(raw_value).split(",") if part.strip()]
    if not values:
        raise ValueError("matrix-k-values must not be empty")
    if any(value <= 0 for value in values):
        raise ValueError("matrix-k-values must be positive integers")
    return values


def _family_quality_loss_specs(
    *,
    generation_size: int,
    include_coded_loss: bool,
) -> list[dict[str, str]]:
    specs: list[dict[str, str]] = []
    for source_index in range(1, int(generation_size) + 1):
        profile = f"drop_g0_s{int(source_index)}"
        specs.append(
            {
                "loss_profile": profile,
                "loss_kind": "single",
                "loss_mix": "systematic_only",
            }
        )
        if include_coded_loss:
            specs.append(
                {
                    "loss_profile": f"{profile}__c0",
                    "loss_kind": "single",
                    "loss_mix": "systematic_plus_coded_loss",
                }
            )
    for source_indices in REPRESENTATIVE_DOUBLE_LOSS_BY_K.get(int(generation_size), ()):
        joined = "-".join(str(int(value)) for value in source_indices)
        profile = f"drop_g0_s{joined}"
        specs.append(
            {
                "loss_profile": profile,
                "loss_kind": "double",
                "loss_mix": "systematic_only",
            }
        )
        if include_coded_loss:
            specs.append(
                {
                    "loss_profile": f"{profile}__c0",
                    "loss_kind": "double",
                    "loss_mix": "systematic_plus_coded_loss",
                }
            )
    for source_indices in REPRESENTATIVE_TRIPLE_LOSS_BY_K.get(int(generation_size), ()):
        joined = "-".join(str(int(value)) for value in source_indices)
        profile = f"drop_g0_s{joined}"
        specs.append(
            {
                "loss_profile": profile,
                "loss_kind": "triple",
                "loss_mix": "systematic_only",
            }
        )
        if include_coded_loss:
            specs.append(
                {
                    "loss_profile": f"{profile}__c0-1",
                    "loss_kind": "triple",
                    "loss_mix": "systematic_plus_coded_loss",
                }
            )
    if include_coded_loss:
        specs.extend(
            [
                {
                    "loss_profile": "drop_g0__c0",
                    "loss_kind": "none",
                    "loss_mix": "coded_only_loss",
                },
                {
                    "loss_profile": "drop_g0__c0-1",
                    "loss_kind": "none",
                    "loss_mix": "coded_only_loss",
                },
            ]
        )
    return specs


def _family_quality_entries(
    *,
    coded_schemes: Sequence[CodingScheme],
    k_values: Sequence[int],
    include_coded_loss: bool,
) -> list[dict[str, int | bool | str]]:
    entries: list[dict[str, int | bool | str]] = []
    for generation_size in k_values:
        entries.append(
            {
                "emit_coded_units": False,
                "coded_redundancy_count": 0,
                "coded_degree": 0,
                "coded_scheme": "",
                "systematic_generation_size": int(generation_size),
                "benchmark_goal": "throughput_completion",
                "loss_profile": "",
                "loss_kind": "none",
                "loss_mix": "none",
                "matrix_label": f"systematic_only_k{int(generation_size)}__throughput",
            }
        )
        for scheme in coded_schemes:
            for redundancy in FORMAL_CODED_REDUNDANCIES:
                for degree in FORMAL_CODED_DEGREES:
                    entries.append(
                        {
                            "emit_coded_units": True,
                            "coded_redundancy_count": int(redundancy),
                            "coded_degree": int(degree),
                            "coded_scheme": scheme.value,
                            "systematic_generation_size": int(generation_size),
                            "benchmark_goal": "throughput_completion",
                            "loss_profile": "",
                            "loss_kind": "none",
                            "loss_mix": "none",
                            "matrix_label": (
                                f"{scheme.value}_k{int(generation_size)}_r{int(redundancy)}_d{int(degree)}"
                                "__throughput"
                            ),
                        }
                    )
                    for loss_spec in _family_quality_loss_specs(
                        generation_size=int(generation_size),
                        include_coded_loss=bool(include_coded_loss),
                    ):
                        entries.append(
                            {
                                "emit_coded_units": True,
                                "coded_redundancy_count": int(redundancy),
                                "coded_degree": int(degree),
                                "coded_scheme": scheme.value,
                                "systematic_generation_size": int(generation_size),
                                "benchmark_goal": "recovery_upper_bound",
                                "loss_profile": str(loss_spec["loss_profile"]),
                                "loss_kind": str(loss_spec["loss_kind"]),
                                "loss_mix": str(loss_spec["loss_mix"]),
                                "matrix_label": (
                                    f"{scheme.value}_k{int(generation_size)}_r{int(redundancy)}_d{int(degree)}"
                                    f"__{str(loss_spec['loss_profile'])}"
                                ),
                            }
                        )
    return entries


def _split_coded_loss_suffix(loss_profile: str) -> tuple[str, list[int]]:
    raw_value = str(loss_profile)
    if "__c" not in raw_value:
        return raw_value, []
    base_profile, coded_suffix = raw_value.split("__c", 1)
    coded_equation_ids = [int(value) for value in coded_suffix.split("-") if value]
    if not coded_equation_ids:
        raise ValueError(f"unsupported loss profile: {loss_profile}")
    return base_profile, coded_equation_ids


def _parse_loss_profile_source_indices(loss_profile: str) -> tuple[int, list[int]] | None:
    if not str(loss_profile).startswith("drop_g"):
        return None
    try:
        generation_part, source_part = (
            str(loss_profile).split("_s", 1)
            if "_s" in str(loss_profile)
            else (str(loss_profile), "")
        )
        generation_id = int(str(generation_part)[len("drop_g") :])
        source_indices = [int(value) for value in str(source_part).split("-") if value]
    except (TypeError, ValueError):
        raise ValueError(f"unsupported loss profile: {loss_profile}")
    if generation_id < 0 or any(index <= 0 for index in source_indices):
        raise ValueError(f"unsupported loss profile: {loss_profile}")
    return generation_id, source_indices


def _protocol_sender_kwargs(protocol: str) -> dict[str, Any]:
    if protocol == "layered":
        return {
            "sync_frames": 4,
            "guard_band_modules": 1,
            "corner_size_modules": 7,
        }
    if protocol in ("compact", "gray4"):
        return {
            "sync_frames": 8,
            "guard_band_modules": 1,
            "corner_size_modules": 7,
        }
    return {
        "sync_frames": 10,
        "guard_band_modules": 2,
        "corner_size_modules": 9,
    }


def _apply_loss_profile(
    items: list[dict[str, Any]],
    *,
    loss_profile: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not loss_profile:
        return list(items), {
            "loss_profile": "",
            "loss_generation_id": -1,
            "dropped_systematic_count": 0,
            "dropped_systematic_chunk_ids": [],
            "dropped_coded_equation_count": 0,
            "dropped_coded_equation_ids": [],
        }

    base_loss_profile, coded_equation_ids = _split_coded_loss_suffix(loss_profile)
    drop_count_map = {
        "drop1_g0": 1,
        "drop2_g0": 2,
        "drop3_g0": 3,
    }
    explicit_profile = _parse_loss_profile_source_indices(base_loss_profile)
    if explicit_profile is None and base_loss_profile not in drop_count_map:
        raise ValueError(f"unsupported loss profile: {loss_profile}")
    drop_count = 0 if explicit_profile is not None else int(drop_count_map[base_loss_profile])
    candidate_chunk_ids_by_generation: dict[int, list[int]] = {}
    candidate_equation_ids_by_generation: dict[int, list[int]] = {}
    for item in items:
        generation_id = int(item.get("generation_id", -1))
        if generation_id < 0:
            continue
        if item.get("plane") == "data" and not bool(item.get("is_coded")):
            chunk_id = int(item.get("chunk_id", -1))
            if chunk_id > 0:
                generation_chunk_ids = candidate_chunk_ids_by_generation.setdefault(generation_id, [])
                if chunk_id not in generation_chunk_ids:
                    generation_chunk_ids.append(chunk_id)
        if item.get("plane") == "data" and bool(item.get("is_coded")):
            equation_id = int(item.get("equation_id", -1))
            if equation_id >= 0:
                generation_equation_ids = candidate_equation_ids_by_generation.setdefault(generation_id, [])
                if equation_id not in generation_equation_ids:
                    generation_equation_ids.append(equation_id)
    if explicit_profile is not None:
        target_generation_id, source_indices = explicit_profile
        candidate_chunk_ids = candidate_chunk_ids_by_generation.get(target_generation_id, [])
        dropped_chunk_ids = set(int(value) for value in source_indices)
        if not dropped_chunk_ids.issubset(set(candidate_chunk_ids)):
            raise ValueError(
            f"loss profile {loss_profile} references source indices not present in generation {target_generation_id}"
            )
    else:
        target_generation_id = -1
        candidate_chunk_ids = []
        for generation_id in sorted(candidate_chunk_ids_by_generation):
            generation_chunk_ids = candidate_chunk_ids_by_generation[generation_id]
            if len(generation_chunk_ids) >= drop_count:
                target_generation_id = generation_id
                candidate_chunk_ids = generation_chunk_ids
                break
        if target_generation_id < 0:
            raise ValueError(
                f"loss profile {loss_profile} requires a generation with at least {drop_count} systematic chunks"
            )
        dropped_chunk_ids = set(candidate_chunk_ids[:drop_count])
    candidate_equation_ids = candidate_equation_ids_by_generation.get(target_generation_id, [])
    dropped_coded_equation_ids = set(int(value) for value in coded_equation_ids)
    if not dropped_coded_equation_ids.issubset(set(candidate_equation_ids)):
        raise ValueError(
            f"loss profile {loss_profile} references coded equations not present in generation {target_generation_id}"
        )
    filtered: list[dict[str, Any]] = []
    seen_dropped: set[int] = set()
    seen_dropped_coded: set[int] = set()
    for item in items:
        if (
            item.get("plane") == "data"
            and not bool(item.get("is_coded"))
            and int(item.get("generation_id", -1)) == target_generation_id
            and int(item.get("chunk_id", -1)) in dropped_chunk_ids
        ):
            seen_dropped.add(int(item.get("chunk_id", -1)))
            continue
        if (
            item.get("plane") == "data"
            and bool(item.get("is_coded"))
            and int(item.get("generation_id", -1)) == target_generation_id
            and int(item.get("equation_id", -1)) in dropped_coded_equation_ids
        ):
            seen_dropped_coded.add(int(item.get("equation_id", -1)))
            continue
        filtered.append(item)
    return filtered, {
        "loss_profile": loss_profile,
        "loss_generation_id": target_generation_id,
        "dropped_systematic_count": len(seen_dropped),
        "dropped_systematic_chunk_ids": sorted(seen_dropped),
        "dropped_coded_equation_count": len(seen_dropped_coded),
        "dropped_coded_equation_ids": sorted(seen_dropped_coded),
    }


def _resolve_loss_plan_from_metadata(
    *,
    metadata: dict[str, Any],
    loss_profile: str,
) -> dict[str, Any]:
    if not loss_profile:
        return {
            "loss_profile": "",
            "loss_generation_id": -1,
            "dropped_systematic_count": 0,
            "dropped_systematic_chunk_ids": [],
            "dropped_coded_equation_count": 0,
            "dropped_coded_equation_ids": [],
        }
    base_loss_profile, coded_equation_ids = _split_coded_loss_suffix(loss_profile)
    drop_count_map = {
        "drop1_g0": 1,
        "drop2_g0": 2,
        "drop3_g0": 3,
    }
    explicit_profile = _parse_loss_profile_source_indices(base_loss_profile)
    generation_plans = list(metadata.get("systematic_generations", []))
    plans_by_generation = {
        int(plan.get("generation_id", -1)): plan
        for plan in generation_plans
        if int(plan.get("generation_id", -1)) >= 0
    }
    if explicit_profile is None and base_loss_profile not in drop_count_map:
        raise ValueError(f"unsupported loss profile: {loss_profile}")
    if explicit_profile is not None:
        target_generation_id, source_indices = explicit_profile
        plan = plans_by_generation.get(int(target_generation_id))
        if plan is None:
            raise ValueError(
                f"loss profile {loss_profile} references generation {target_generation_id} not present in metadata"
            )
        generation_size = int(plan.get("generation_size", 0))
        dropped_chunk_ids = sorted(int(value) for value in source_indices)
        if not dropped_chunk_ids or any(index <= 0 or index > generation_size for index in dropped_chunk_ids):
            raise ValueError(
                f"loss profile {loss_profile} references source indices not present in generation {target_generation_id}"
            )
    else:
        drop_count = int(drop_count_map[base_loss_profile])
        target_generation_id = -1
        generation_size = 0
        for plan in generation_plans:
            candidate_generation_id = int(plan.get("generation_id", -1))
            candidate_generation_size = int(plan.get("generation_size", 0))
            if candidate_generation_size >= drop_count:
                target_generation_id = candidate_generation_id
                generation_size = candidate_generation_size
                break
        if target_generation_id < 0:
            raise ValueError(
                f"loss profile {loss_profile} requires a generation with at least {drop_count} systematic chunks"
            )
        dropped_chunk_ids = list(range(1, drop_count + 1))
    plan = plans_by_generation.get(int(target_generation_id), {})
    coded_redundancy_count = int(plan.get("coded_redundancy_count", 0))
    dropped_coded_equation_ids = sorted(int(value) for value in coded_equation_ids)
    if any(equation_id < 0 or equation_id >= coded_redundancy_count for equation_id in dropped_coded_equation_ids):
        raise ValueError(
            f"loss profile {loss_profile} references coded equations not present in generation {target_generation_id}"
        )
    return {
        "loss_profile": loss_profile,
        "loss_generation_id": int(target_generation_id),
        "dropped_systematic_count": len(dropped_chunk_ids),
        "dropped_systematic_chunk_ids": dropped_chunk_ids,
        "dropped_coded_equation_count": len(dropped_coded_equation_ids),
        "dropped_coded_equation_ids": dropped_coded_equation_ids,
    }


def _theoretical_recoverability_diagnostics(
    *,
    emitted_items: list[dict[str, Any]],
    received_items: list[dict[str, Any]],
    metadata: dict[str, Any],
    loss_info: dict[str, Any],
) -> dict[str, Any]:
    target_generation_id = int(loss_info.get("loss_generation_id", -1))
    lost_source_indices = list(loss_info.get("dropped_systematic_chunk_ids", []))
    lost_coded_equation_ids = list(loss_info.get("dropped_coded_equation_ids", []))
    if target_generation_id < 0 or not lost_source_indices:
        return {
            "lost_source_indices": [],
            "lost_coded_equation_ids": list(lost_coded_equation_ids),
            "target_generation_size": 0,
            "target_generation_coded_equation_count": 0,
            "target_generation_coded_scheme": "",
            "emitted_equation_supports": [],
            "received_equation_supports": [],
            "support_union_size": 0,
            "missing_symbol_coverage_count_min": 0,
            "missing_symbol_coverage_count_max": 0,
            "all_missing_symbols_covered": False,
            "ideal_equation_count_ge_missing": False,
            "theoretical_recoverable_by_coverage_bound": False,
            "received_equation_count_ge_missing": False,
            "received_all_missing_symbols_covered": False,
            "theoretical_recoverable_after_coded_loss": False,
        }
    generation_size = 0
    for plan in metadata.get("systematic_generations", []):
        if int(plan.get("generation_id", -1)) == target_generation_id:
            generation_size = int(plan.get("generation_size", 0))
            break
    emitted_coded_items = [
        item
        for item in emitted_items
        if bool(item.get("is_coded"))
        and int(item.get("generation_id", -1)) == target_generation_id
    ]
    received_coded_items = [
        item
        for item in received_items
        if bool(item.get("is_coded"))
        and int(item.get("generation_id", -1)) == target_generation_id
    ]
    emitted_equation_supports = [
        [
            source_index
            for source_index, _coefficient in expand_equation_terms(
                generation_size=generation_size,
                coding_seed=int(item.get("coding_seed", 0)),
                degree=int(item.get("degree", 0)),
                coding_scheme=CodingScheme(str(item.get("coding_scheme", ""))),
            )
        ]
        for item in emitted_coded_items
        if generation_size > 0
    ]
    received_equation_supports = [
        [
            source_index
            for source_index, _coefficient in expand_equation_terms(
                generation_size=generation_size,
                coding_seed=int(item.get("coding_seed", 0)),
                degree=int(item.get("degree", 0)),
                coding_scheme=CodingScheme(str(item.get("coding_scheme", ""))),
            )
        ]
        for item in received_coded_items
        if generation_size > 0
    ]
    support_union = sorted(
        {
            source_index
            for support in emitted_equation_supports
            for source_index in support
        }
    )
    missing_coverage_counts = [
        sum(1 for support in emitted_equation_supports if int(source_index) in support)
        for source_index in lost_source_indices
    ]
    received_missing_coverage_counts = [
        sum(1 for support in received_equation_supports if int(source_index) in support)
        for source_index in lost_source_indices
    ]
    target_generation_coded_scheme = ""
    if emitted_coded_items:
        target_generation_coded_scheme = str(emitted_coded_items[0].get("coding_scheme", "") or "")
    elif int(metadata.get("emit_coded_units", 0)):
        target_generation_coded_scheme = str(metadata.get("coded_scheme", "") or "")
    all_missing_symbols_covered = bool(missing_coverage_counts) and all(
        int(count) > 0 for count in missing_coverage_counts
    )
    received_all_missing_symbols_covered = bool(received_missing_coverage_counts) and all(
        int(count) > 0 for count in received_missing_coverage_counts
    )
    ideal_equation_count_ge_missing = len(emitted_equation_supports) >= len(lost_source_indices)
    received_equation_count_ge_missing = len(received_equation_supports) >= len(lost_source_indices)
    return {
        "lost_source_indices": sorted(int(value) for value in lost_source_indices),
        "lost_coded_equation_ids": sorted(int(value) for value in lost_coded_equation_ids),
        "target_generation_size": int(generation_size),
        "target_generation_coded_equation_count": len(emitted_equation_supports),
        "target_generation_coded_scheme": target_generation_coded_scheme,
        "emitted_equation_supports": emitted_equation_supports,
        "received_equation_supports": received_equation_supports,
        "support_union_size": len(support_union),
        "missing_symbol_coverage_count_min": min(missing_coverage_counts) if missing_coverage_counts else 0,
        "missing_symbol_coverage_count_max": max(missing_coverage_counts) if missing_coverage_counts else 0,
        "all_missing_symbols_covered": bool(all_missing_symbols_covered),
        "ideal_equation_count_ge_missing": bool(ideal_equation_count_ge_missing),
        "theoretical_recoverable_by_coverage_bound": bool(
            all_missing_symbols_covered and ideal_equation_count_ge_missing
        ),
        "received_equation_count_ge_missing": bool(received_equation_count_ge_missing),
        "received_all_missing_symbols_covered": bool(received_all_missing_symbols_covered),
        "theoretical_recoverable_after_coded_loss": bool(
            received_all_missing_symbols_covered and received_equation_count_ge_missing
        ),
    }


def _safe_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values)) / float(len(values))


def _case_int(case: dict[str, int | bool | str], key: str, default: int) -> int:
    raw_value = case.get(key, default)
    return int(default if raw_value is None else raw_value)


def _write_incremental_outputs(
    *,
    results: list[dict[str, Any]],
    output_json: str,
    summary_json: str,
    planned_entries: Sequence[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    summary = _summarize_results(results, planned_entries=planned_entries)
    if output_json:
        Path(output_json).write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if summary_json:
        Path(summary_json).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return summary


def _summary_group_key(row: dict[str, Any]) -> tuple[str, int, int, int, str, str, str]:
    return (
        str(row.get("coded_scheme", "")),
        int(row.get("systematic_generation_size", 0)),
        int(row.get("coded_degree", 0)),
        int(row.get("coded_redundancy_count", 0)),
        str(row.get("loss_kind", "none")),
        str(row.get("loss_mix", "none")),
        str(row.get("benchmark_goal", "")),
    )


def _summarize_results(
    results: list[dict[str, Any]],
    *,
    planned_entries: Sequence[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int, int, int, str, str, str], list[dict[str, Any]]] = {}
    planned_counts: dict[tuple[str, int, int, int, str, str, str], int] = {}
    for row in planned_entries or ():
        group_key = _summary_group_key(row)
        planned_counts[group_key] = planned_counts.get(group_key, 0) + 1
    for row in results:
        group_key = _summary_group_key(row)
        groups.setdefault(group_key, []).append(row)
        planned_counts[group_key] = planned_counts.get(group_key, 0) + 0

    summary_rows: list[dict[str, Any]] = []
    for group_key in sorted(set(planned_counts) | set(groups)):
        group_rows = groups.get(group_key, [])
        coded_scheme, generation_size, degree, redundancy, loss_kind, loss_mix, benchmark_goal = group_key
        restore_success_count = sum(1 for row in group_rows if bool(row.get("restore_success", False)))
        coverage_bound_recoverable_count = sum(
            1 for row in group_rows if bool(row.get("theoretical_recoverable_by_coverage_bound", False))
        )
        theory_vs_observed_gap_count = sum(
            1
            for row in group_rows
            if bool(row.get("theoretical_recoverable_after_coded_loss", False))
            and not bool(row.get("restore_success", False))
        )
        budget_exhausted_count = sum(
            1 for row in group_rows if str(row.get("termination_kind", "")) == "budget_exhausted"
        )
        single_rows = [row for row in group_rows if str(row.get("loss_kind", "")) == "single"]
        double_rows = [row for row in group_rows if str(row.get("loss_kind", "")) == "double"]
        single_coverages = [float(row.get("missing_symbol_coverage_count_min", 0)) for row in single_rows]
        coverage_uniformity_score = 0.0
        if single_coverages and max(single_coverages) > 0:
            coverage_uniformity_score = float(min(single_coverages)) / float(max(single_coverages))
        planned_case_count = max(int(planned_counts.get(group_key, 0)), len(group_rows))
        completed_case_count = len(group_rows)
        summary_rows.append(
            {
                "coded_scheme": coded_scheme,
                "systematic_generation_size": generation_size,
                "coded_degree": degree,
                "coded_redundancy_count": redundancy,
                "loss_kind": loss_kind,
                "loss_mix": loss_mix,
                "benchmark_goal": benchmark_goal,
                "case_count": planned_case_count,
                "completed_case_count": completed_case_count,
                "pending_case_count": max(0, planned_case_count - completed_case_count),
                "has_observed_results": bool(group_rows),
                "restore_success_count": restore_success_count,
                "restore_success_rate": (
                    float(restore_success_count) / float(completed_case_count)
                    if completed_case_count > 0
                    else 0.0
                ),
                "coverage_bound_recoverable_count": coverage_bound_recoverable_count,
                "coverage_bound_recoverable_rate": (
                    float(coverage_bound_recoverable_count) / float(completed_case_count)
                    if completed_case_count > 0
                    else 0.0
                ),
                "theory_vs_observed_gap_count": theory_vs_observed_gap_count,
                "budget_exhausted_count": budget_exhausted_count,
                "mean_missing_chunks_after_budget": _safe_mean(
                    [float(row.get("missing_chunks", 0)) for row in group_rows]
                ),
                "mean_coded_units_seen": _safe_mean(
                    [float(row.get("coded_units_seen", 0)) for row in group_rows]
                ),
                "mean_solver_rank_peak": _safe_mean(
                    [float(row.get("solver_rank_peak", 0)) for row in group_rows]
                ),
                "mean_recovery_efficiency": _safe_mean(
                    [float(row.get("recovery_efficiency", 0.0)) for row in group_rows]
                ),
                "mean_coded_visibility_ratio": _safe_mean(
                    [float(row.get("coded_visibility_ratio", 0.0)) for row in group_rows]
                ),
                "single_loss_theoretical_coverage_rate": (
                    _safe_mean(
                        [
                            1.0 if bool(row.get("theoretical_recoverable_by_coverage_bound", False)) else 0.0
                            for row in single_rows
                        ]
                    )
                    if single_rows
                    else 0.0
                ),
                "single_loss_restore_rate": (
                    _safe_mean([1.0 if bool(row.get("restore_success", False)) else 0.0 for row in single_rows])
                    if single_rows
                    else 0.0
                ),
                "double_loss_theoretical_coverage_rate": (
                    _safe_mean(
                        [
                            1.0 if bool(row.get("theoretical_recoverable_by_coverage_bound", False)) else 0.0
                            for row in double_rows
                        ]
                    )
                    if double_rows
                    else 0.0
                ),
                "double_loss_restore_rate": (
                    _safe_mean([1.0 if bool(row.get("restore_success", False)) else 0.0 for row in double_rows])
                    if double_rows
                    else 0.0
                ),
                "coverage_uniformity_score": coverage_uniformity_score,
            }
        )
    return summary_rows


def _protocol_chunk_size(config: ProtocolConfig, ecc_level: str, payload_mode: str, payload_size: int) -> int:
    layout = make_encoder(config, ecc_level).get_layout()
    return payload_size_for_mode(layout, payload_mode, payload_size)


def _normalize_replay_outcome(status: str) -> tuple[str, str]:
    if status == "ok":
        return ("completed", "restored")
    if status == "timeout_idle":
        return ("budget_exhausted", "incomplete_after_budget")
    if status == "timeout_max_seconds":
        return ("runtime_guard_timeout", "harness_failure")
    return ("aborted", "harness_failure")


def _run_replay_case(
    config: ProtocolConfig,
    layout_mode: str,
    ecc_level: str,
    payload_mode: str,
    payload_size: int,
    fps: int,
    stats_interval: float,
    benchmark_seconds: int,
    benchmark_goal: str,
    max_idle_seconds: int,
    runtime_guard_seconds: int,
    decode_workers: int,
    replay_geometry_mode: str,
    source_mode: str,
    simulated_live_pacing: str,
    input_path: str,
    emit_coded_units: bool = False,
    coded_redundancy_count: int = 0,
    coded_degree: int = 2,
    coded_scheme: str = CodingScheme.GF256_SEED_V2.value,
    loss_profile: str = "",
    compress: str = "none",
    systematic_generation_size: int = 6,
    frame_width: int = 1920,
    frame_height: int = 1080,
) -> dict[str, Any]:
    chunk_size = _protocol_chunk_size(config, ecc_level, payload_mode, payload_size)
    coding_scheme = CodingScheme(str(coded_scheme))
    sender_kwargs = _protocol_sender_kwargs(config.protocol)
    with tempfile.TemporaryDirectory(prefix="sa-e2e-") as td:
        tmp = Path(td)
        frame_dir = tmp / "frames"
        frame_dir.mkdir()
        out_dir = tmp / "out"
        report_path = tmp / "report.json"
        epochs = 1
        stream = build_encoded_frames(
            input_path=input_path,
            chunk_size=chunk_size,
            compress=compress,
            epochs=epochs,
            width=frame_width,
            height=frame_height,
            protocol=config.protocol,
            module_grid=f"{config.grid_w}x{config.grid_h}",
            ecc_level=ecc_level,
            systematic_generation_size=systematic_generation_size,
            emit_coded_units=emit_coded_units,
            coded_redundancy_count=coded_redundancy_count,
            coded_degree=coded_degree,
            coded_scheme=coding_scheme,
            **sender_kwargs,
        )
        metadata: dict[str, Any] | None = None
        loss_info: dict[str, Any] | None = None
        target_generation_id = -1
        dropped_systematic_ids: set[int] = set()
        dropped_coded_ids: set[int] = set()
        emitted_items: list[dict[str, Any]] = []
        received_items: list[dict[str, Any]] = []
        written_frame_count = 0
        for item in stream:
            if metadata is None:
                metadata = dict(item.get("metadata", {}))
                loss_info = _resolve_loss_plan_from_metadata(
                    metadata=metadata,
                    loss_profile=loss_profile,
                )
                target_generation_id = int(loss_info.get("loss_generation_id", -1))
                dropped_systematic_ids = set(int(value) for value in loss_info.get("dropped_systematic_chunk_ids", []))
                dropped_coded_ids = set(int(value) for value in loss_info.get("dropped_coded_equation_ids", []))
            should_drop = False
            if (
                item.get("plane") == "data"
                and not bool(item.get("is_coded"))
                and int(item.get("generation_id", -1)) == target_generation_id
                and int(item.get("chunk_id", -1)) in dropped_systematic_ids
            ):
                should_drop = True
            if (
                item.get("plane") == "data"
                and bool(item.get("is_coded"))
                and int(item.get("generation_id", -1)) == target_generation_id
                and int(item.get("equation_id", -1)) in dropped_coded_ids
            ):
                should_drop = True
            if (
                bool(item.get("is_coded"))
                and int(item.get("generation_id", -1)) == target_generation_id
            ):
                coded_item = {
                    "generation_id": int(item.get("generation_id", -1)),
                    "equation_id": int(item.get("equation_id", -1)),
                    "coding_seed": int(item.get("coding_seed", 0)),
                    "degree": int(item.get("degree", 0)),
                    "coding_scheme": str(item.get("coding_scheme", "")),
                }
                emitted_items.append(coded_item)
                if not should_drop:
                    received_items.append(coded_item)
            if should_drop:
                continue
            np.save(frame_dir / f"{written_frame_count:06d}.npy", item["image"])
            written_frame_count += 1
        if metadata is None or loss_info is None:
            raise RuntimeError("build_encoded_frames produced no items")
        theoretical_diagnostics = _theoretical_recoverability_diagnostics(
            emitted_items=emitted_items,
            received_items=received_items,
            metadata=metadata,
            loss_info=loss_info,
        )

        started = time.time()
        code = receiver_main(
            [
                "--source",
                str(source_mode),
                "--frames-dir",
                str(frame_dir),
                "--output-dir",
                str(out_dir),
                "--protocol",
                config.protocol,
                "--module-grid",
                f"{config.grid_w}x{config.grid_h}",
                "--stats-interval",
                str(stats_interval),
                "--max-idle-seconds",
                str(max_idle_seconds),
                "--max-seconds",
                str(runtime_guard_seconds),
                "--report-json",
                str(report_path),
                "--decode-workers",
                str(int(decode_workers)),
                "--replay-geometry-mode",
                str(replay_geometry_mode),
                "--simulated-live-pacing",
                str(simulated_live_pacing),
            ]
        )
        elapsed = max(1e-6, time.time() - started)
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        status = str(report.get("status", ""))
        termination_kind, result_class = _normalize_replay_outcome(status)
        coded_units_seen = int(report.get("coded_units_seen", 0))
        coded_units_duplicate = int(report.get("coded_units_duplicate", 0))
        coded_units_invalid = int(report.get("coded_units_invalid", 0))
        coded_units_conflicting = int(report.get("coded_units_conflicting", 0))
        coded_units_dependent = int(report.get("coded_units_dependent", 0))
        solver_rank_peak = int(report.get("solver_rank_peak", 0))
        recovered_source_symbols = int(report.get("recovered_source_symbols", 0))
        missing_chunks = int(report.get("missing_chunks", 0))
        payload_chunk_count = int(metadata.get("payload_chunk_count", 0))
        valid_frames = int(report.get("valid_frames", 0))
        assembled_bytes = int(report.get("assembled_bytes", 0))
        output_size_bytes = int(report.get("output_size_bytes", 0))
        startup_control_frames_decoded = int(report.get("startup_control_frames_decoded", 0))
        systematic_generations = list(metadata.get("systematic_generations", []))
        configured_generation_size = int(metadata.get("systematic_generation_size", 0))
        coded_generations_skipped = sum(
            1
            for plan in systematic_generations
            if str(plan.get("coded_emission_mode", "")).startswith("skipped_")
        )
        short_generation_count = sum(
            1
            for plan in systematic_generations
            if int(plan.get("generation_size", 0)) < configured_generation_size
        )
        coded_short_generation_count = sum(
            1
            for plan in systematic_generations
            if int(plan.get("generation_size", 0)) < configured_generation_size
            and str(plan.get("coded_emission_mode", "")) == "enabled"
        )
        report.update(
            {
                "benchmark_kind": "end_to_end_replay",
                "protocol": config.protocol,
                "config": protocol_config_dict(config),
                "layout_mode": layout_mode,
                "ecc_level": ecc_level,
                "payload_mode": payload_mode,
                "payload_bytes": chunk_size,
                "compress": compress,
                "fps": fps,
                "benchmark_seconds": benchmark_seconds,
                "benchmark_budget_kind": "finite_replay",
                "benchmark_goal": benchmark_goal,
                "max_idle_seconds": int(max_idle_seconds),
                "runtime_guard_seconds": int(runtime_guard_seconds),
                "decode_workers": int(decode_workers),
                "runtime_mode": str(report.get("runtime_mode", source_mode)),
                "producer_mode": str(report.get("producer_mode", "frames_dir")),
                "source_mode": str(source_mode),
                "simulated_live_pacing": str(simulated_live_pacing),
                "replay_geometry_mode": str(replay_geometry_mode),
                "systematic_generation_size": int(systematic_generation_size),
                "frame_width": frame_width,
                "frame_height": frame_height,
                "stats_interval": stats_interval,
                "loss_profile": str(loss_info["loss_profile"]),
                "loss_generation_id": int(loss_info["loss_generation_id"]),
                "dropped_systematic_count": int(loss_info["dropped_systematic_count"]),
                "dropped_systematic_chunk_ids": list(loss_info["dropped_systematic_chunk_ids"]),
                "dropped_coded_equation_count": int(loss_info["dropped_coded_equation_count"]),
                "dropped_coded_equation_ids": list(loss_info["dropped_coded_equation_ids"]),
                "loss_injected": bool(
                    int(loss_info["dropped_systematic_count"]) or int(loss_info["dropped_coded_equation_count"])
                ),
                "termination_kind": termination_kind,
                "result_class": result_class,
                "recovery_limit_reached": bool(status == "timeout_idle"),
                "all_replay_frames_consumed": bool(status == "timeout_idle"),
                "completed_transfer": bool(status == "ok"),
                "restore_success": bool(status == "ok"),
                "recovery_success": bool(status == "ok"),
                "tx_payload_kib_per_s": float(chunk_size * fps / 1024.0),
                "rx_payload_kib_per_s": float(report.get("goodput_kibps", report.get("goodput_kbps", 0.0))),
                "benchmark_elapsed_s": elapsed,
                "completion_elapsed_s": elapsed,
                "tx_payload_kib_per_s_effective": (
                    float(output_size_bytes) / 1024.0 / elapsed if output_size_bytes > 0 else 0.0
                ),
                "rx_goodput_kib_per_s_effective": float(
                    report.get("goodput_kibps", report.get("goodput_kbps", 0.0))
                ),
                "decode_progress_kib_per_s": (
                    float(assembled_bytes) / 1024.0 / elapsed if assembled_bytes > 0 else 0.0
                ),
                "frame_consumption_fps_effective": (
                    float(valid_frames) / elapsed if valid_frames > 0 else 0.0
                ),
                "exit_code": code,
                "frame_payload_cap": metadata.get("frame_payload_cap", 0),
                "effective_chunk_size": metadata.get("effective_chunk_size", chunk_size),
                "epochs_rendered": epochs,
                "sender_epochs": epochs,
                "sender_budget_frame_count": int(written_frame_count),
                "sync_frames": int(metadata.get("schedule", {}).get("sync_frames", 0)),
                "control_burst_repeat": int(
                    metadata.get("schedule", {}).get("control_burst_repeat", 0)
                ),
                "data_realizations": int(metadata.get("schedule", {}).get("data_realizations", 0)),
                "emit_coded_units": bool(metadata.get("emit_coded_units", False)),
                "coded_redundancy_count": int(metadata.get("coded_redundancy_count", 0)),
                "coded_degree": int(metadata.get("coded_degree", 0)),
                "coded_scheme": str(metadata.get("coded_scheme", "")),
                "coded_units_emitted": int(metadata.get("coded_unit_count", 0)),
                "coded_generations_skipped": int(coded_generations_skipped),
                "short_generation_count": int(short_generation_count),
                "coded_short_generation_count": int(coded_short_generation_count),
                "coded_units_seen": coded_units_seen,
                "coded_units_duplicate": coded_units_duplicate,
                "coded_units_invalid": coded_units_invalid,
                "coded_units_conflicting": coded_units_conflicting,
                "coded_units_dependent": coded_units_dependent,
                "solver_rank_peak": solver_rank_peak,
                "recovered_source_symbols": recovered_source_symbols,
                "missing_chunks": missing_chunks,
                "observed_restore_success": bool(status == "ok"),
                "observed_budget_exhausted": bool(status == "timeout_idle"),
                "observed_missing_chunks_after_budget": missing_chunks,
                "systematic_generations": systematic_generations,
                "matrix_label": "",
                "matrix_case_index": 0,
                "matrix_case_count": 1,
                "recovery_progress_ratio": (
                    float(max(0, payload_chunk_count - missing_chunks)) / float(payload_chunk_count)
                    if payload_chunk_count > 0
                    else 0.0
                ),
                "coded_visibility_ratio": (
                    float(coded_units_seen) / float(int(metadata.get("coded_unit_count", 0)))
                    if int(metadata.get("coded_unit_count", 0)) > 0
                    else 0.0
                ),
                "recovery_efficiency": (
                    float(recovered_source_symbols) / float(coded_units_seen)
                    if coded_units_seen > 0
                    else 0.0
                ),
                "rank_efficiency": (
                    float(solver_rank_peak) / float(coded_units_seen)
                    if coded_units_seen > 0
                    else 0.0
                ),
                "startup_overhead_ratio": (
                    float(startup_control_frames_decoded) / float(valid_frames)
                    if valid_frames > 0
                    else 0.0
                ),
                "redundancy_efficiency": (
                    float(recovered_source_symbols) / float(coded_units_seen)
                    if coded_units_seen > 0
                    else 0.0
                ),
                "duplicate_equation_rate": (
                    float(coded_units_duplicate) / float(coded_units_seen)
                    if coded_units_seen > 0
                    else 0.0
                ),
                **theoretical_diagnostics,
            }
        )
        return report


def _screen_runbook_case(
    config: ProtocolConfig,
    layout_mode: str,
    ecc_level: str,
    payload_mode: str,
    payload_size: int,
    fps: int,
    capture_fps: int,
    benchmark_seconds: int,
    benchmark_goal: str,
    max_idle_seconds: int,
    runtime_guard_seconds: int,
    stats_interval: float,
    input_path: str,
    emit_coded_units: bool = False,
    coded_redundancy_count: int = 0,
    coded_degree: int = 2,
    coded_scheme: str = CodingScheme.GF256_SEED_V2.value,
    compress: str = "none",
    systematic_generation_size: int = 6,
    frame_width: int = 1920,
    frame_height: int = 1080,
) -> dict[str, Any]:
    chunk_size = _protocol_chunk_size(config, ecc_level, payload_mode, payload_size)
    frame_size_args = ""
    if (frame_width, frame_height) != (1920, 1080):
        frame_size_args = f" --frame-width {frame_width} --frame-height {frame_height}"
    coded_args = ""
    if bool(emit_coded_units):
        coded_args = (
            f" --emit-coded-units --coded-redundancy-count {int(coded_redundancy_count)}"
            f" --coded-degree {int(coded_degree)}"
        )
    return {
        "benchmark_kind": "end_to_end_screen_runbook",
        "protocol": config.protocol,
        "config": protocol_config_dict(config),
        "layout_mode": layout_mode,
        "ecc_level": ecc_level,
        "payload_mode": payload_mode,
        "payload_bytes": chunk_size,
        "compress": compress,
        "fps": fps,
        "capture_fps": capture_fps,
        "benchmark_seconds": benchmark_seconds,
        "benchmark_budget_kind": "finite_replay",
        "benchmark_goal": benchmark_goal,
        "max_idle_seconds": int(max_idle_seconds),
        "runtime_guard_seconds": int(runtime_guard_seconds),
        "systematic_generation_size": int(systematic_generation_size),
        "frame_width": frame_width,
        "frame_height": frame_height,
        "stats_interval": stats_interval,
        "loss_profile": "",
        "loss_generation_id": -1,
        "dropped_systematic_count": 0,
        "dropped_systematic_chunk_ids": [],
        "dropped_coded_equation_count": 0,
        "dropped_coded_equation_ids": [],
        "loss_injected": False,
        "loss_kind": "none",
        "loss_mix": "none",
        "emit_coded_units": bool(emit_coded_units),
        "coded_redundancy_count": int(coded_redundancy_count),
        "coded_degree": int(coded_degree),
        "coded_scheme": str(coded_scheme) if bool(emit_coded_units) else "",
        "matrix_label": "",
        "matrix_case_index": 0,
        "matrix_case_count": 1,
        "sender_command": (
            f"uv run screen-airdrop-sender {input_path} --protocol {config.protocol} "
            f"--module-grid {config.grid_w}x{config.grid_h} --ecc-level {ecc_level} "
            f"--fps {fps} --chunk-size {chunk_size} --compress {compress} --max-epochs 1 "
            f"{frame_size_args} --stats-interval {stats_interval}"
            f"{coded_args}"
        ),
        "receiver_command": (
            f"uv run screen-airdrop-receiver --source screen --protocol {config.protocol} "
            f"--module-grid {config.grid_w}x{config.grid_h} --roi-interactive "
            f"--capture-fps {capture_fps} --stats-interval {stats_interval} "
            f"--max-idle-seconds {int(max_idle_seconds)} --max-seconds {int(runtime_guard_seconds)} "
            f"--output-dir ./recovered_{config.protocol}_{ecc_level}_{payload_mode}"
        ),
    }


def main() -> int:
    args = parse_args()
    ecc_levels = list(ECC_LEVELS) if args.ecc == "all" else [args.ecc]
    configs = protocol_configs(args.protocol, args.layout_mode)
    k_values = _parse_matrix_k_values(args.matrix_k_values)
    selected_coded_schemes = (
        list(FORMAL_CODED_SCHEMES)
        if bool(args.compare_coded_schemes)
        else [CodingScheme(str(args.coded_scheme))]
    )
    family_quality_enabled = bool(args.family_quality_matrix)
    matrix_cases = _coded_matrix_cases(
        enabled=bool(args.coded_matrix or args.lossy_coded_matrix),
        coded_schemes=selected_coded_schemes,
    )
    loss_profiles = _loss_profiles(enabled=bool(args.lossy_coded_matrix))
    benchmark_goal = (
        "recovery_upper_bound"
        if bool(args.lossy_coded_matrix)
        else str(args.benchmark_goal)
    )

    planned_entries: list[dict[str, Any]] = []
    # `planned_entries` tracks the full matrix shape so summary output is non-empty
    # before the first completion-run case finishes.
    for config in configs:
        for ecc_level in ecc_levels:
            if family_quality_enabled:
                planned_entries.extend(
                    _family_quality_entries(
                        coded_schemes=selected_coded_schemes,
                        k_values=k_values,
                        include_coded_loss=bool(args.include_coded_loss),
                    )
                )
            else:
                case_inputs = (
                    matrix_cases
                    if bool(args.coded_matrix or args.lossy_coded_matrix)
                    else [
                        {
                            "emit_coded_units": bool(args.emit_coded_units),
                            "coded_redundancy_count": int(args.coded_redundancy_count),
                            "coded_degree": int(args.coded_degree),
                            "coded_scheme": str(args.coded_scheme) if bool(args.emit_coded_units) else "",
                            "matrix_label": "",
                        }
                    ]
                )
                for loss_profile in loss_profiles:
                    for case in case_inputs:
                        planned_entries.append(
                            {
                                **case,
                                "systematic_generation_size": int(args.systematic_generation_size),
                                "benchmark_goal": benchmark_goal,
                                "loss_profile": str(loss_profile),
                                "loss_kind": "none" if not loss_profile else str(loss_profile).split("_", 1)[0],
                                "loss_mix": "systematic_only" if loss_profile else "none",
                            }
                        )

    if args.output_json:
        Path(args.output_json).write_text("[]\n", encoding="utf-8")
    if args.summary_json:
        Path(args.summary_json).write_text(
            json.dumps(_summarize_results([], planned_entries=planned_entries), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    results = []
    for config in configs:
        for ecc_level in ecc_levels:
            if family_quality_enabled:
                matrix_entries = _family_quality_entries(
                    coded_schemes=selected_coded_schemes,
                    k_values=k_values,
                    include_coded_loss=bool(args.include_coded_loss),
                )
            else:
                case_inputs = (
                    matrix_cases
                    if bool(args.coded_matrix or args.lossy_coded_matrix)
                    else [
                        {
                            "emit_coded_units": bool(args.emit_coded_units),
                            "coded_redundancy_count": int(args.coded_redundancy_count),
                            "coded_degree": int(args.coded_degree),
                            "coded_scheme": str(args.coded_scheme) if bool(args.emit_coded_units) else "",
                            "matrix_label": "",
                        }
                    ]
                )
                matrix_entries = []
                for loss_profile in loss_profiles:
                    for case in case_inputs:
                        matrix_entries.append(
                            {
                                **case,
                                "systematic_generation_size": int(args.systematic_generation_size),
                                "benchmark_goal": benchmark_goal,
                                "loss_profile": str(loss_profile),
                                "loss_kind": "none" if not loss_profile else str(loss_profile).split("_", 1)[0],
                                "loss_mix": "systematic_only" if loss_profile else "none",
                            }
                        )
            total_case_count = len(matrix_entries)
            for matrix_index, case in enumerate(matrix_entries):
                row_goal = str(case.get("benchmark_goal", benchmark_goal))
                if args.mode == "replay":
                    result = _run_replay_case(
                        config=config,
                        layout_mode=args.layout_mode,
                        ecc_level=ecc_level,
                        payload_mode=args.payload_mode,
                        payload_size=args.payload_size,
                        fps=args.fps,
                        benchmark_seconds=args.benchmark_seconds,
                        benchmark_goal=row_goal,
                        max_idle_seconds=args.max_idle_seconds,
                        runtime_guard_seconds=args.runtime_guard_seconds,
                        stats_interval=args.stats_interval,
                        input_path=args.input,
                        decode_workers=args.decode_workers,
                        replay_geometry_mode=args.replay_geometry_mode,
                        source_mode=args.source_mode,
                        simulated_live_pacing=args.simulated_live_pacing,
                        compress=args.compress,
                        systematic_generation_size=_case_int(
                            case, "systematic_generation_size", int(args.systematic_generation_size)
                        ),
                        emit_coded_units=bool(case["emit_coded_units"]),
                        coded_redundancy_count=int(case["coded_redundancy_count"]),
                        coded_degree=int(case["coded_degree"]),
                        coded_scheme=str(case.get("coded_scheme") or args.coded_scheme),
                        loss_profile=str(case.get("loss_profile", "")),
                    )
                else:
                    result = _screen_runbook_case(
                        config=config,
                        layout_mode=args.layout_mode,
                        ecc_level=ecc_level,
                        payload_mode=args.payload_mode,
                        payload_size=args.payload_size,
                        fps=args.fps,
                        capture_fps=args.capture_fps,
                        benchmark_seconds=args.benchmark_seconds,
                        benchmark_goal=row_goal,
                        max_idle_seconds=args.max_idle_seconds,
                        runtime_guard_seconds=args.runtime_guard_seconds,
                        stats_interval=args.stats_interval,
                        input_path=args.input,
                        compress=args.compress,
                        systematic_generation_size=_case_int(
                            case, "systematic_generation_size", int(args.systematic_generation_size)
                        ),
                        emit_coded_units=bool(case["emit_coded_units"]),
                        coded_redundancy_count=int(case["coded_redundancy_count"]),
                        coded_degree=int(case["coded_degree"]),
                        coded_scheme=str(case.get("coded_scheme") or args.coded_scheme),
                    )
                result["loss_kind"] = str(case.get("loss_kind", result.get("loss_kind", "none")))
                result["loss_mix"] = str(case.get("loss_mix", result.get("loss_mix", "none")))
                result["matrix_label"] = str(case["matrix_label"])
                result["matrix_case_index"] = int(matrix_index)
                result["matrix_case_count"] = int(total_case_count)
                results.append(result)
                print(json.dumps(result, ensure_ascii=False))
                _write_incremental_outputs(
                    results=results,
                    output_json=str(args.output_json),
                    summary_json=str(args.summary_json),
                    planned_entries=planned_entries,
                )

    out_path = write_json_result(f"end_to_end_{args.mode}_benchmark", results)
    summary = _write_incremental_outputs(
        results=results,
        output_json=str(args.output_json),
        summary_json=str(args.summary_json),
        planned_entries=planned_entries,
    )
    summary_path = write_json_result(f"end_to_end_{args.mode}_benchmark_summary", summary)
    for row in summary:
        print("SUMMARY", json.dumps(row, ensure_ascii=False))
    print("Saved:", out_path)
    print("Saved summary:", summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
