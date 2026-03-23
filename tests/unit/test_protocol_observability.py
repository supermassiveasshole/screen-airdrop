# pyright: reportIndexIssue=false, reportOperatorIssue=false
from __future__ import annotations

from types import SimpleNamespace

from screen_airdrop.receiver.transport.layered.observability import (
    Gray4ReportAdapter,
    LayeredReportAdapter,
)


def test_gray4_report_adapter_accumulates_success_and_failure():
    adapter = Gray4ReportAdapter()
    adapter.accumulate_success(
        SimpleNamespace(
            mask_id=3,
            avg_symbol_confidence=0.9,
            total_decode_ms=12.5,
            payload_low_conf_symbols=2,
            payload_variant_attempts=1,
            phase_candidates_tried=3,
            phase_sweep_used=True,
        )
    )
    adapter.accumulate_failure("payload crc mismatch")
    summary = adapter.finalize_summary()
    assert summary["gray4_failure_counts"]["payload"] == 1
    assert "protocol_debug" in summary
    assert "gray4_debug" in summary["protocol_debug"]


def test_layered_report_adapter_accumulates_trace_and_failures():
    adapter = LayeredReportAdapter()
    adapter.accumulate_success(
        SimpleNamespace(
            body_profile_id=3,
            body_profile_name="dense",
            control_trace={
                "bootstrap_attempt_count": 1,
                "bootstrap_threshold": 0,
                "bootstrap_vote_margin_min": 4.0,
                "bootstrap_vote_margin_avg": 8.0,
                "bootstrap_erasure_symbol_count": 2,
                "bootstrap_rs_corrected": 1,
                "bootstrap_template_best_score_avg": 1.5,
                "bootstrap_template_margin_avg": 8.0,
                "control_reference_decode_mode": "reference_templates",
                "control_band_decode_stage": "ok",
            }
        )
    )
    adapter.accumulate_failure(
        "bootstrap rs decode failed",
        trace={
            "bootstrap_attempt_count": 1,
            "bootstrap_threshold": 0,
            "bootstrap_vote_margin_min": 1.0,
            "bootstrap_vote_margin_avg": 3.0,
            "bootstrap_erasure_symbol_count": 3,
            "bootstrap_rs_corrected": 0,
            "bootstrap_template_best_score_avg": 6.5,
            "bootstrap_template_margin_avg": 3.0,
            "control_reference_decode_mode": "reference_templates",
            "control_band_decode_stage": "bootstrap_rs",
            "dibits": [0] * 8,
        },
    )
    summary = adapter.finalize_summary()
    assert summary["layered_core_header_rs_fail_count"] == 1.0
    assert summary["layered_control_reference_decode_mode"] == "reference_templates"
    assert summary["layered_body_profile_id"] == 3.0
    assert summary["layered_body_ecc_profile_id"] == 3.0
    assert summary["layered_bootstrap_template_best_score_avg"] > 0.0
    assert "layered_debug" in summary["protocol_debug"]
    layered_debug = summary["protocol_debug"]["layered_debug"]
    assert layered_debug["core_header"]["erasure_symbol_count_avg"] > 0
    assert layered_debug["body"]["profile_name"] == "dense"
