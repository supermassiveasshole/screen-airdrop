import json

import numpy as np
from bench.benchmark_common import ProtocolConfig, make_decoder, make_encoder
from bench.compare_end_to_end import (
    _apply_loss_profile,
    _coded_matrix_cases,
    _family_quality_entries,
    _loss_profiles,
    _parse_matrix_k_values,
    _run_replay_case,
    _screen_runbook_case,
    _summarize_results,
)
from bench.compare_protocols import benchmark_protocol

from screen_airdrop.common.information import CodingScheme


def test_screen_runbook_case_contains_controlled_commands():
    config = ProtocolConfig("compact", grid_w=166, grid_h=102)
    result = _screen_runbook_case(
        config=config,
        layout_mode="footprint_matched",
        ecc_level="Q",
        payload_mode="max",
        payload_size=500,
        fps=12,
        capture_fps=30,
        benchmark_seconds=45,
        benchmark_goal="throughput_completion",
        max_idle_seconds=3,
        runtime_guard_seconds=0,
        stats_interval=1.0,
        input_path="tests/fixtures/real_data/regular_pdf",
        compress="none",
        systematic_generation_size=6,
    )

    assert result["benchmark_kind"] == "end_to_end_screen_runbook"
    assert result["benchmark_goal"] == "throughput_completion"
    assert result["benchmark_seconds"] == 45
    assert result["layout_mode"] == "footprint_matched"
    assert "--protocol compact" in result["sender_command"]
    assert "--module-grid 166x102" in result["sender_command"]
    assert "--chunk-size 594" in result["sender_command"]
    assert "--compress none" in result["sender_command"]
    assert "--max-epochs 1" in result["sender_command"]
    assert "regular_pdf" in result["sender_command"]
    assert "--roi-interactive" in result["receiver_command"]
    assert "--max-idle-seconds 3" in result["receiver_command"]
    assert "--max-seconds 0" in result["receiver_command"]


def test_synthetic_benchmark_reports_payload_efficiency():
    config = ProtocolConfig("basic", grid_w=160, grid_h=96)
    encoder = make_encoder(config, "Q")
    decoder = make_decoder(config)
    result = benchmark_protocol(
        protocol_name=config.protocol,
        config=config,
        encoder=encoder,
        decoder=decoder,
        ecc_level="Q",
        layout_mode="same_grid",
        payload_mode="fixed",
        payload_size=500,
        iterations=1,
        width=1920,
        height=1080,
    )

    assert result["benchmark_kind"] == "synthetic_cpu"
    assert result["payload_bytes"] == 500
    assert result["payload_bits_per_module"] > 0
    assert result["synthetic_cpu_kib_per_s"] > 0


def test_replay_case_reports_erasure_comparison_fields(monkeypatch, tmp_path):
    config = ProtocolConfig("basic", grid_w=160, grid_h=96)

    metadata = {
        "frame_payload_cap": 512,
        "effective_chunk_size": 256,
        "emit_coded_units": True,
        "coded_redundancy_count": 2,
        "coded_degree": 3,
        "coded_scheme": "gf256_seed_v2",
        "coded_unit_count": 4,
        "systematic_generation_size": 6,
        "systematic_generations": [
            {
                "generation_id": 0,
                "generation_size": 6,
                "coded_emission_mode": "enabled",
                "coded_degree_effective": 3,
            },
            {
                "generation_id": 1,
                "generation_size": 4,
                "coded_emission_mode": "enabled",
                "coded_degree_effective": 4,
            },
        ],
    }

    def _fake_build_encoded_frames(**kwargs):
        del kwargs
        return [
            {"metadata": metadata, "image": np.zeros((4, 4), dtype=np.uint8)},
            {"metadata": metadata, "image": np.zeros((4, 4), dtype=np.uint8)},
        ]

    def _fake_receiver_main(argv):
        report_path = argv[argv.index("--report-json") + 1]
        assert argv[argv.index("--source") + 1] == "simulated_live"
        assert argv[argv.index("--decode-workers") + 1] == "4"
        assert argv[argv.index("--replay-geometry-mode") + 1] == "stateless"
        assert argv[argv.index("--simulated-live-pacing") + 1] == "none"
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "status": "ok",
                    "goodput_kibps": 12.5,
                    "runtime_mode": "simulated_live",
                    "producer_mode": "frames_dir",
                    "coded_units_seen": 4,
                    "coded_units_duplicate": 1,
                    "coded_units_invalid": 0,
                    "coded_units_conflicting": 0,
                    "coded_units_dependent": 2,
                    "solver_rank_peak": 2,
                    "recovered_source_symbols": 2,
                    "missing_chunks": 0,
                },
                handle,
            )
        return 0

    monkeypatch.setattr("bench.compare_end_to_end.build_encoded_frames", _fake_build_encoded_frames)
    monkeypatch.setattr("bench.compare_end_to_end.receiver_main", _fake_receiver_main)

    result = _run_replay_case(
        config=config,
        layout_mode="same_grid",
        ecc_level="Q",
        payload_mode="fixed",
        payload_size=500,
        fps=12,
        stats_interval=1.0,
        benchmark_seconds=1,
        benchmark_goal="throughput_completion",
        max_idle_seconds=3,
        runtime_guard_seconds=0,
        decode_workers=4,
        replay_geometry_mode="stateless",
        source_mode="simulated_live",
        simulated_live_pacing="none",
        input_path=str(tmp_path / "payload.bin"),
    )

    assert result["restore_success"] is True
    assert result["recovery_success"] is True
    assert result["termination_kind"] == "completed"
    assert result["result_class"] == "restored"
    assert result["benchmark_goal"] == "throughput_completion"
    assert result["decode_workers"] == 4
    assert result["runtime_mode"] == "simulated_live"
    assert result["producer_mode"] == "frames_dir"
    assert result["source_mode"] == "simulated_live"
    assert result["replay_geometry_mode"] == "stateless"
    assert result["all_replay_frames_consumed"] is False
    assert result["coded_generations_skipped"] == 0
    assert result["coded_scheme"] == "gf256_seed_v2"
    assert result["matrix_label"] == ""
    assert result["coded_units_seen"] == 4
    assert result["coded_units_duplicate"] == 1
    assert result["coded_units_dependent"] == 2
    assert result["solver_rank_peak"] == 2
    assert result["recovered_source_symbols"] == 2
    assert result["short_generation_count"] == 1
    assert result["coded_short_generation_count"] == 1
    assert result["loss_profile"] == ""
    assert result["dropped_systematic_count"] == 0
    assert result["loss_injected"] is False
    assert result["redundancy_efficiency"] == 0.5
    assert result["duplicate_equation_rate"] == 0.25
    assert result["completion_elapsed_s"] > 0
    assert result["sender_budget_frame_count"] == 2
    assert result["sender_epochs"] == 1
    assert result["systematic_generations"][1]["coded_degree_effective"] == 4
    assert result["lost_source_indices"] == []
    assert result["theoretical_recoverable_by_coverage_bound"] is False


def test_replay_case_normalizes_timeout_idle_as_budget_exhausted(monkeypatch, tmp_path):
    config = ProtocolConfig("basic", grid_w=160, grid_h=96)

    metadata = {
        "frame_payload_cap": 512,
        "effective_chunk_size": 256,
        "emit_coded_units": False,
        "coded_redundancy_count": 0,
        "coded_degree": 0,
        "coded_scheme": "",
        "coded_unit_count": 0,
        "payload_chunk_count": 6,
        "schedule": {"sync_frames": 8, "control_burst_repeat": 5, "data_realizations": 1},
        "systematic_generation_size": 6,
        "systematic_generations": [
            {
                "generation_id": 0,
                "generation_size": 6,
                "coded_emission_mode": "disabled",
                "coded_degree_effective": 0,
            }
        ],
    }

    def _fake_build_encoded_frames(**kwargs):
        del kwargs
        return [{"metadata": metadata, "image": np.zeros((4, 4), dtype=np.uint8)}]

    def _fake_receiver_main(argv):
        report_path = argv[argv.index("--report-json") + 1]
        assert argv[argv.index("--source") + 1] == "simulated_live"
        assert argv[argv.index("--max-seconds") + 1] == "0"
        assert argv[argv.index("--max-idle-seconds") + 1] == "3"
        assert argv[argv.index("--decode-workers") + 1] == "4"
        assert argv[argv.index("--replay-geometry-mode") + 1] == "stateless"
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "status": "timeout_idle",
                    "goodput_kibps": 0.0,
                    "valid_frames": 4,
                    "assembled_bytes": 512,
                    "output_size_bytes": 0,
                    "startup_control_frames_decoded": 2,
                    "missing_chunks": 2,
                },
                handle,
            )
        return 2

    monkeypatch.setattr("bench.compare_end_to_end.build_encoded_frames", _fake_build_encoded_frames)
    monkeypatch.setattr("bench.compare_end_to_end.receiver_main", _fake_receiver_main)

    result = _run_replay_case(
        config=config,
        layout_mode="same_grid",
        ecc_level="Q",
        payload_mode="fixed",
        payload_size=500,
        fps=12,
        stats_interval=1.0,
        benchmark_seconds=1,
        benchmark_goal="recovery_upper_bound",
        max_idle_seconds=3,
        runtime_guard_seconds=0,
        decode_workers=4,
        replay_geometry_mode="stateless",
        source_mode="simulated_live",
        simulated_live_pacing="none",
        input_path=str(tmp_path / "payload.bin"),
    )

    assert result["restore_success"] is False
    assert result["termination_kind"] == "budget_exhausted"
    assert result["result_class"] == "incomplete_after_budget"
    assert result["recovery_limit_reached"] is True
    assert result["all_replay_frames_consumed"] is True


def test_coded_matrix_cases_expand_to_formal_baseline_grid():
    cases = _coded_matrix_cases(enabled=True)

    assert cases[0] == {
        "emit_coded_units": False,
        "coded_redundancy_count": 0,
        "coded_degree": 0,
        "coded_scheme": "",
        "matrix_label": "systematic_only",
    }
    coded_cases = cases[1:]
    assert len(coded_cases) == 9
    assert {case["coded_redundancy_count"] for case in coded_cases} == {1, 2, 4}
    assert {case["coded_degree"] for case in coded_cases} == {2, 3, 4}
    assert {case["coded_scheme"] for case in coded_cases} == {"gf256_seed_v2"}
    assert all(case["emit_coded_units"] is True for case in coded_cases)


def test_coded_matrix_cases_can_compare_v1_and_v2():
    cases = _coded_matrix_cases(
        enabled=True,
        coded_schemes=[CodingScheme.GF256_SEED_V1, CodingScheme.GF256_SEED_V2],
    )

    coded_cases = cases[1:]

    assert len(coded_cases) == 18
    assert {case["coded_scheme"] for case in coded_cases} == {
        "gf256_seed_v1",
        "gf256_seed_v2",
    }


def test_loss_profiles_expand_to_fixed_drop_set():
    assert _loss_profiles(enabled=False) == [""]
    assert _loss_profiles(enabled=True) == ["drop1_g0", "drop2_g0", "drop3_g0"]


def test_parse_matrix_k_values_parses_csv():
    assert _parse_matrix_k_values("4,6,8") == [4, 6, 8]


def test_apply_loss_profile_drops_generation_zero_systematics_only():
    items = [
        {"plane": "data", "is_coded": False, "generation_id": 0, "chunk_id": 1, "image": None},
        {"plane": "data", "is_coded": False, "generation_id": 0, "chunk_id": 2, "image": None},
        {"plane": "data", "is_coded": False, "generation_id": 0, "chunk_id": 3, "image": None},
        {"plane": "data", "is_coded": True, "generation_id": 0, "chunk_id": 1, "image": None},
        {"plane": "data", "is_coded": False, "generation_id": 1, "chunk_id": 1, "image": None},
    ]

    filtered, info = _apply_loss_profile(items, loss_profile="drop2_g0")

    assert info["loss_profile"] == "drop2_g0"
    assert info["loss_generation_id"] == 0
    assert info["dropped_systematic_count"] == 2
    assert info["dropped_systematic_chunk_ids"] == [1, 2]
    remaining = [
        (item["generation_id"], item["chunk_id"], bool(item["is_coded"]))
        for item in filtered
    ]
    assert (0, 1, False) not in remaining
    assert (0, 2, False) not in remaining
    assert (0, 1, True) in remaining
    assert (1, 1, False) in remaining


def test_apply_loss_profile_can_drop_coded_equations_too():
    items = [
        {"plane": "data", "is_coded": False, "generation_id": 0, "chunk_id": 1, "image": None},
        {"plane": "data", "is_coded": False, "generation_id": 0, "chunk_id": 2, "image": None},
        {"plane": "data", "is_coded": True, "generation_id": 0, "equation_id": 0, "chunk_id": 1, "image": None},
        {"plane": "data", "is_coded": True, "generation_id": 0, "equation_id": 1, "chunk_id": 2, "image": None},
    ]

    filtered, info = _apply_loss_profile(items, loss_profile="drop_g0_s1__c0")

    assert info["dropped_systematic_chunk_ids"] == [1]
    assert info["dropped_coded_equation_ids"] == [0]
    remaining = [
        (item["generation_id"], item.get("chunk_id"), item.get("equation_id"), bool(item["is_coded"]))
        for item in filtered
    ]
    assert (0, 1, None, False) not in remaining
    assert (0, 1, 0, True) not in remaining
    assert (0, 2, 1, True) in remaining


def test_family_quality_entries_include_throughput_and_lossy_rows():
    entries = _family_quality_entries(
        coded_schemes=[CodingScheme.GF256_SEED_V2],
        k_values=[4],
        include_coded_loss=True,
    )

    assert any(entry["benchmark_goal"] == "throughput_completion" for entry in entries)
    assert any(entry["loss_mix"] == "systematic_plus_coded_loss" for entry in entries)
    assert any(entry["loss_mix"] == "coded_only_loss" for entry in entries)
    assert any(entry["systematic_generation_size"] == 4 for entry in entries)


def test_summarize_results_aggregates_restore_and_coverage_rates():
    summary = _summarize_results(
        [
            {
                "coded_scheme": "gf256_seed_v2",
                "systematic_generation_size": 4,
                "coded_degree": 2,
                "coded_redundancy_count": 1,
                "loss_kind": "single",
                "loss_mix": "systematic_only",
                "benchmark_goal": "recovery_upper_bound",
                "restore_success": True,
                "theoretical_recoverable_by_coverage_bound": True,
                "theoretical_recoverable_after_coded_loss": True,
                "termination_kind": "completed",
                "missing_chunks": 0,
                "coded_units_seen": 2,
                "solver_rank_peak": 1,
                "recovery_efficiency": 0.5,
                "coded_visibility_ratio": 1.0,
                "missing_symbol_coverage_count_min": 2,
            },
            {
                "coded_scheme": "gf256_seed_v2",
                "systematic_generation_size": 4,
                "coded_degree": 2,
                "coded_redundancy_count": 1,
                "loss_kind": "single",
                "loss_mix": "systematic_only",
                "benchmark_goal": "recovery_upper_bound",
                "restore_success": False,
                "theoretical_recoverable_by_coverage_bound": False,
                "theoretical_recoverable_after_coded_loss": False,
                "termination_kind": "budget_exhausted",
                "missing_chunks": 1,
                "coded_units_seen": 1,
                "solver_rank_peak": 0,
                "recovery_efficiency": 0.0,
                "coded_visibility_ratio": 1.0,
                "missing_symbol_coverage_count_min": 1,
            },
        ]
    )

    assert len(summary) == 1
    row = summary[0]
    assert row["case_count"] == 2
    assert row["restore_success_count"] == 1
    assert row["coverage_bound_recoverable_count"] == 1
    assert row["budget_exhausted_count"] == 1
    assert row["single_loss_restore_rate"] == 0.5
    assert row["coverage_uniformity_score"] == 0.5


def test_summarize_results_can_emit_planned_groups_before_results_exist():
    summary = _summarize_results(
        [],
        planned_entries=[
            {
                "coded_scheme": "gf256_seed_v2",
                "systematic_generation_size": 4,
                "coded_degree": 2,
                "coded_redundancy_count": 1,
                "loss_kind": "single",
                "loss_mix": "systematic_only",
                "benchmark_goal": "recovery_upper_bound",
            }
        ],
    )

    assert len(summary) == 1
    row = summary[0]
    assert row["case_count"] == 1
    assert row["completed_case_count"] == 0
    assert row["pending_case_count"] == 1
    assert row["has_observed_results"] is False
    assert row["restore_success_rate"] == 0.0
