# pyright: reportArgumentType=false
"""Protocol-specific observability adapters for receiver reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from screen_airdrop.common.ecc_rs import LAYERED_BOOTSTRAP_RS
from screen_airdrop.common.protocol_layered import (
    LAYERED_CONTROL_PATH_VERSION,
    layered_body_ecc_profile,
    layered_bootstrap_payload_size_bytes,
)


def _classify_gray4_decode_failure(decode_error: Optional[str]) -> str:
    raw = "" if decode_error is None else str(decode_error).strip().lower()
    if not raw:
        return ""
    if "payload rs decode failed" in raw or "payload crc mismatch" in raw or "crc mismatch" in raw:
        return "payload"
    if "header rs decode failed" in raw or "bad v3 magic" in raw or "format parity mismatch" in raw:
        return "header"
    if "locator" in raw or "no_finder" in raw or "finder" in raw:
        return "locator"
    return "unknown"


def _classify_layered_decode_failure_detail(decode_error: str) -> str:
    raw = str(decode_error or "").strip().lower()
    if "bootstrap template match failed" in raw:
        return "bootstrap_template_match"
    if "control prefix" in raw:
        return "control_prefix"
    if "format parity mismatch" in raw:
        return "format"
    if "bootstrap rs decode failed" in raw:
        return "bootstrap_rs"
    if "bootstrap crc mismatch" in raw:
        return "bootstrap_crc"
    if "body rs decode failed" in raw:
        return "body_rs"
    if "body crc mismatch" in raw or "payload crc mismatch" in raw:
        return "body_crc"
    return "unknown"


class ProtocolReportAdapter:
    protocol: str = ""

    def empty_snapshot(self) -> Dict[str, object]:
        return {}

    def accumulate_success(self, meta: Any) -> None:
        return None

    def accumulate_failure(
        self,
        error: str,
        *,
        failure_class: str = "",
        trace: Optional[Mapping[str, object]] = None,
    ) -> None:
        return None

    def finalize_summary(self) -> Dict[str, object]:
        return {}


class NoOpProtocolReportAdapter(ProtocolReportAdapter):
    pass


@dataclass
class Gray4ReportAdapter(ProtocolReportAdapter):
    protocol: str = "gray4"
    failure_counts: Dict[str, int] = field(
        default_factory=lambda: {"header": 0, "payload": 0, "locator": 0, "unknown": 0}
    )
    last_failure_error: str = ""
    last_failure_class: str = ""
    last_mask_id: float = -1.0
    avg_symbol_confidence: float = 0.0
    total_decode_ms: float = 0.0
    payload_low_conf_symbols: int = 0
    payload_variant_attempts: int = 0
    phase_candidates_tried: int = 0
    phase_sweep_used: bool = False

    def accumulate_success(self, meta: Any) -> None:
        self.last_mask_id = float(getattr(meta, "mask_id", -1))
        self.avg_symbol_confidence = float(getattr(meta, "avg_symbol_confidence", 0.0))
        self.total_decode_ms = float(getattr(meta, "total_decode_ms", 0.0))
        self.payload_low_conf_symbols = int(getattr(meta, "payload_low_conf_symbols", 0))
        self.payload_variant_attempts = int(getattr(meta, "payload_variant_attempts", 0))
        self.phase_candidates_tried = int(getattr(meta, "phase_candidates_tried", 0))
        self.phase_sweep_used = bool(getattr(meta, "phase_sweep_used", False))

    def accumulate_failure(
        self,
        error: str,
        *,
        failure_class: str = "",
        trace: Optional[Mapping[str, object]] = None,
    ) -> None:
        del trace
        failure_class = failure_class or _classify_gray4_decode_failure(error)
        self.last_failure_error = str(error or "")
        self.last_failure_class = str(failure_class or "")
        if failure_class in self.failure_counts:
            self.failure_counts[failure_class] += 1
        elif failure_class:
            self.failure_counts["unknown"] += 1

    def empty_snapshot(self) -> Dict[str, object]:
        return {
            "gray4_last_failure_error": "",
            "gray4_last_failure_class": "",
            "gray4_failure_counts": dict(self.failure_counts),
            "gray4_last_mask_id": -1.0,
            "gray4_avg_symbol_confidence": 0.0,
            "gray4_total_decode_ms": 0.0,
            "gray4_payload_low_conf_symbols": 0.0,
            "gray4_payload_variant_attempts": 0.0,
            "gray4_phase_candidates_tried": 0.0,
            "gray4_phase_sweep_used": 0.0,
            "protocol_debug": {
                "gray4_debug": {
                    "failure_counts": dict(self.failure_counts),
                    "last_failure_error": "",
                    "last_failure_class": "",
                    "last_mask_id": -1.0,
                    "avg_symbol_confidence": 0.0,
                    "total_decode_ms": 0.0,
                    "payload_low_conf_symbols": 0,
                    "payload_variant_attempts": 0,
                    "phase_candidates_tried": 0,
                    "phase_sweep_used": False,
                }
            },
        }

    def finalize_summary(self) -> Dict[str, object]:
        debug = {
            "failure_counts": dict(self.failure_counts),
            "last_failure_error": self.last_failure_error,
            "last_failure_class": self.last_failure_class,
            "last_mask_id": self.last_mask_id,
            "avg_symbol_confidence": self.avg_symbol_confidence,
            "total_decode_ms": self.total_decode_ms,
            "payload_low_conf_symbols": self.payload_low_conf_symbols,
            "payload_variant_attempts": self.payload_variant_attempts,
            "phase_candidates_tried": self.phase_candidates_tried,
            "phase_sweep_used": self.phase_sweep_used,
        }
        return {
            "gray4_last_failure_error": self.last_failure_error,
            "gray4_last_failure_class": self.last_failure_class,
            "gray4_failure_counts": dict(self.failure_counts),
            "gray4_last_mask_id": self.last_mask_id,
            "gray4_avg_symbol_confidence": self.avg_symbol_confidence,
            "gray4_total_decode_ms": self.total_decode_ms,
            "gray4_payload_low_conf_symbols": float(self.payload_low_conf_symbols),
            "gray4_payload_variant_attempts": float(self.payload_variant_attempts),
            "gray4_phase_candidates_tried": float(self.phase_candidates_tried),
            "gray4_phase_sweep_used": 1.0 if self.phase_sweep_used else 0.0,
            "protocol_debug": {"gray4_debug": debug},
        }


@dataclass
class LayeredReportAdapter(ProtocolReportAdapter):
    protocol: str = "layered"
    control_path_version: int = LAYERED_CONTROL_PATH_VERSION
    bootstrap_attempt_count: int = 0
    bootstrap_threshold_sum: float = 0.0
    bootstrap_threshold_count: int = 0
    bootstrap_vote_margin_sum: float = 0.0
    bootstrap_vote_margin_count: int = 0
    bootstrap_vote_margin_min: float = 0.0
    bootstrap_erasure_symbol_count_sum: float = 0.0
    bootstrap_erasure_symbol_count_count: int = 0
    bootstrap_erasure_symbol_count_max: int = 0
    bootstrap_errata_corrected_sum: float = 0.0
    bootstrap_errata_corrected_count: int = 0
    bootstrap_errata_corrected_max: int = 0
    bootstrap_bit_fail_counts: List[int] = field(default_factory=list)
    bootstrap_fail_examples: List[Dict[str, object]] = field(default_factory=list)
    bootstrap_rs_fail_count: int = 0
    bootstrap_crc_fail_count: int = 0
    body_rs_fail_count: int = 0
    body_crc_fail_count: int = 0
    decode_stage_counts: Dict[str, int] = field(default_factory=dict)
    body_profile_id: int = 0
    body_profile_name: str = ""
    body_ecc_profile_id: int = 0
    control_reference_decode_mode: str = ""
    bootstrap_template_best_score_sum: float = 0.0
    bootstrap_template_best_score_count: int = 0
    bootstrap_template_best_score_min: float = 0.0
    bootstrap_template_margin_sum: float = 0.0
    bootstrap_template_margin_count: int = 0
    bootstrap_template_margin_min: float = 0.0

    @staticmethod
    def _trace_attempts(trace: Mapping[str, object]) -> List[Mapping[str, object]]:
        attempts = trace.get("attempts")
        if isinstance(attempts, list):
            return [attempt for attempt in attempts if isinstance(attempt, Mapping)]
        return []

    def _accumulate_trace(self, trace: Mapping[str, object], *, is_failure: bool) -> None:
        attempts = self._trace_attempts(trace)
        reference_mode = str(trace.get("control_reference_decode_mode", "") or "")
        if reference_mode:
            self.control_reference_decode_mode = reference_mode
        self.bootstrap_attempt_count += int(trace.get("bootstrap_attempt_count", 0) or len(attempts))
        if attempts:
            for attempt in attempts:
                if "threshold_value" in attempt:
                    self.bootstrap_threshold_sum += float(attempt.get("threshold_value", 0) or 0.0)
                    self.bootstrap_threshold_count += 1
                vote_margin_min = float(attempt.get("vote_margin_min", 0.0) or 0.0)
                vote_margin_avg = float(attempt.get("vote_margin_avg", 0.0) or 0.0)
                if self.bootstrap_vote_margin_count <= 0:
                    self.bootstrap_vote_margin_min = vote_margin_min
                else:
                    self.bootstrap_vote_margin_min = min(self.bootstrap_vote_margin_min, vote_margin_min)
                self.bootstrap_vote_margin_sum += vote_margin_avg
                self.bootstrap_vote_margin_count += 1
                erasure_count = int(attempt.get("erasure_symbol_count", 0) or 0)
                self.bootstrap_erasure_symbol_count_sum += float(erasure_count)
                self.bootstrap_erasure_symbol_count_count += 1
                self.bootstrap_erasure_symbol_count_max = max(
                    self.bootstrap_erasure_symbol_count_max, erasure_count
                )
                template_best_score = float(attempt.get("template_best_score_avg", 0.0) or 0.0)
                if self.bootstrap_template_best_score_count <= 0:
                    self.bootstrap_template_best_score_min = template_best_score
                else:
                    self.bootstrap_template_best_score_min = min(
                        self.bootstrap_template_best_score_min, template_best_score
                    )
                self.bootstrap_template_best_score_sum += template_best_score
                self.bootstrap_template_best_score_count += 1
                template_margin = float(attempt.get("template_margin_avg", 0.0) or 0.0)
                if self.bootstrap_template_margin_count <= 0:
                    self.bootstrap_template_margin_min = template_margin
                else:
                    self.bootstrap_template_margin_min = min(self.bootstrap_template_margin_min, template_margin)
                self.bootstrap_template_margin_sum += template_margin
                self.bootstrap_template_margin_count += 1
                stage = str(attempt.get("decode_stage", "") or "")
                if stage:
                    self.decode_stage_counts[stage] = self.decode_stage_counts.get(stage, 0) + 1
                bits = attempt.get("binary_bits")
                if is_failure and isinstance(bits, list):
                    if not self.bootstrap_bit_fail_counts:
                        self.bootstrap_bit_fail_counts = [0] * len(bits)
                    disagree = attempt.get("disagree_bit_positions", [])
                    if isinstance(disagree, list):
                        for idx in disagree:
                            if isinstance(idx, int) and 0 <= idx < len(self.bootstrap_bit_fail_counts):
                                self.bootstrap_bit_fail_counts[idx] += 1
        else:
            if "bootstrap_threshold" in trace:
                self.bootstrap_threshold_sum += float(trace.get("bootstrap_threshold", 0) or 0.0)
                self.bootstrap_threshold_count += 1
            vote_margin_min = float(trace.get("bootstrap_vote_margin_min", 0.0) or 0.0)
            vote_margin_avg = float(trace.get("bootstrap_vote_margin_avg", 0.0) or 0.0)
            if self.bootstrap_vote_margin_count <= 0:
                self.bootstrap_vote_margin_min = vote_margin_min
            else:
                self.bootstrap_vote_margin_min = min(self.bootstrap_vote_margin_min, vote_margin_min)
            self.bootstrap_vote_margin_sum += vote_margin_avg
            self.bootstrap_vote_margin_count += 1
            erasure_count = int(trace.get("bootstrap_erasure_symbol_count", 0) or 0)
            self.bootstrap_erasure_symbol_count_sum += float(erasure_count)
            self.bootstrap_erasure_symbol_count_count += 1
            self.bootstrap_erasure_symbol_count_max = max(self.bootstrap_erasure_symbol_count_max, erasure_count)
            template_best_score = float(trace.get("bootstrap_template_best_score_avg", 0.0) or 0.0)
            if self.bootstrap_template_best_score_count <= 0:
                self.bootstrap_template_best_score_min = template_best_score
            else:
                self.bootstrap_template_best_score_min = min(
                    self.bootstrap_template_best_score_min, template_best_score
                )
            self.bootstrap_template_best_score_sum += template_best_score
            self.bootstrap_template_best_score_count += 1
            template_margin = float(trace.get("bootstrap_template_margin_avg", 0.0) or 0.0)
            if self.bootstrap_template_margin_count <= 0:
                self.bootstrap_template_margin_min = template_margin
            else:
                self.bootstrap_template_margin_min = min(self.bootstrap_template_margin_min, template_margin)
            self.bootstrap_template_margin_sum += template_margin
            self.bootstrap_template_margin_count += 1
            stage = str(trace.get("control_band_decode_stage", "") or "")
            if stage:
                self.decode_stage_counts[stage] = self.decode_stage_counts.get(stage, 0) + 1
            bits = trace.get("bootstrap_bits")
            if is_failure and isinstance(bits, list):
                if not self.bootstrap_bit_fail_counts:
                    self.bootstrap_bit_fail_counts = [0] * len(bits)
                disagree = trace.get("disagree_bit_positions", [])
                if isinstance(disagree, list):
                    for idx in disagree:
                        if isinstance(idx, int) and 0 <= idx < len(self.bootstrap_bit_fail_counts):
                            self.bootstrap_bit_fail_counts[idx] += 1
        errata = int(trace.get("bootstrap_rs_corrected", 0) or 0)
        self.bootstrap_errata_corrected_sum += float(errata)
        self.bootstrap_errata_corrected_count += 1
        self.bootstrap_errata_corrected_max = max(self.bootstrap_errata_corrected_max, errata)
        if is_failure and len(self.bootstrap_fail_examples) < 8:
            self.bootstrap_fail_examples.append(dict(trace))

    def accumulate_success(self, meta: Any) -> None:
        trace = getattr(meta, "control_trace", None)
        if isinstance(trace, Mapping):
            self._accumulate_trace(trace, is_failure=False)
        self.body_profile_id = int(getattr(meta, "body_profile_id", self.body_profile_id) or 0)
        self.body_profile_name = str(getattr(meta, "body_profile_name", self.body_profile_name) or "")
        if self.body_profile_id:
            self.body_ecc_profile_id = int(layered_body_ecc_profile(self.body_profile_id).profile_id)

    def accumulate_failure(
        self,
        error: str,
        *,
        failure_class: str = "",
        trace: Optional[Mapping[str, object]] = None,
    ) -> None:
        del failure_class
        detail = _classify_layered_decode_failure_detail(error)
        if detail == "bootstrap_rs":
            self.bootstrap_rs_fail_count += 1
        elif detail == "bootstrap_crc":
            self.bootstrap_crc_fail_count += 1
        elif detail == "bootstrap_template_match":
            self.decode_stage_counts[detail] = self.decode_stage_counts.get(detail, 0) + 1
        elif detail == "body_rs":
            self.body_rs_fail_count += 1
        elif detail == "body_crc":
            self.body_crc_fail_count += 1
        if trace is not None:
            self._accumulate_trace(trace, is_failure=True)
        elif detail:
            self.decode_stage_counts[detail] = self.decode_stage_counts.get(detail, 0) + 1

    def empty_snapshot(self) -> Dict[str, object]:
        return self.finalize_summary()

    def finalize_summary(self) -> Dict[str, object]:
        core_debug = {
            "raw_bytes": int(layered_bootstrap_payload_size_bytes()),
            "coded_bytes": int(layered_bootstrap_payload_size_bytes() + int(LAYERED_BOOTSTRAP_RS.nsym)),
            "ecc_nsym": int(LAYERED_BOOTSTRAP_RS.nsym),
            "attempt_count": int(self.bootstrap_attempt_count),
            "threshold_avg": 0.0
            if self.bootstrap_threshold_count <= 0
            else self.bootstrap_threshold_sum / float(self.bootstrap_threshold_count),
            "vote_margin_min": float(self.bootstrap_vote_margin_min),
            "vote_margin_avg": 0.0
            if self.bootstrap_vote_margin_count <= 0
            else self.bootstrap_vote_margin_sum / float(self.bootstrap_vote_margin_count),
            "template_best_score_avg": 0.0
            if self.bootstrap_template_best_score_count <= 0
            else self.bootstrap_template_best_score_sum / float(self.bootstrap_template_best_score_count),
            "template_best_score_min": float(self.bootstrap_template_best_score_min),
            "template_margin_avg": 0.0
            if self.bootstrap_template_margin_count <= 0
            else self.bootstrap_template_margin_sum / float(self.bootstrap_template_margin_count),
            "template_margin_min": float(self.bootstrap_template_margin_min),
            "erasure_symbol_count_avg": 0.0
            if self.bootstrap_erasure_symbol_count_count <= 0
            else self.bootstrap_erasure_symbol_count_sum / float(self.bootstrap_erasure_symbol_count_count),
            "erasure_symbol_count_max": int(self.bootstrap_erasure_symbol_count_max),
            "errata_corrected_avg": 0.0
            if self.bootstrap_errata_corrected_count <= 0
            else self.bootstrap_errata_corrected_sum / float(self.bootstrap_errata_corrected_count),
            "errata_corrected_max": int(self.bootstrap_errata_corrected_max),
            "rs_fail_count": int(self.bootstrap_rs_fail_count),
            "crc_fail_count": int(self.bootstrap_crc_fail_count),
            "fail_examples": list(self.bootstrap_fail_examples),
        }
        layered_debug = {
            "control_path_version": int(self.control_path_version),
            "control_reference_decode_mode": self.control_reference_decode_mode,
            "core_header": core_debug,
            "body": {
                "profile_id": int(self.body_profile_id),
                "profile_name": self.body_profile_name,
                "ecc_profile_id": int(self.body_ecc_profile_id),
                "rs_fail_count": int(self.body_rs_fail_count),
                "crc_fail_count": int(self.body_crc_fail_count),
            },
            "decode_stage_counts": dict(self.decode_stage_counts),
        }
        return {
            "layered_control_path_version": float(self.control_path_version),
            "layered_core_header_raw_bytes": float(core_debug["raw_bytes"]),
            "layered_core_header_coded_bytes": float(core_debug["coded_bytes"]),
            "layered_core_header_ecc_nsym": float(core_debug["ecc_nsym"]),
            "layered_core_header_attempt_count": float(core_debug["attempt_count"]),
            "layered_core_header_threshold_avg": float(core_debug["threshold_avg"]),
            "layered_core_header_vote_margin_min": float(core_debug["vote_margin_min"]),
            "layered_core_header_vote_margin_avg": float(core_debug["vote_margin_avg"]),
            "layered_core_header_erasure_symbol_count_avg": float(core_debug["erasure_symbol_count_avg"]),
            "layered_core_header_erasure_symbol_count_max": float(core_debug["erasure_symbol_count_max"]),
            "layered_core_header_errata_corrected_avg": float(core_debug["errata_corrected_avg"]),
            "layered_core_header_errata_corrected_max": float(core_debug["errata_corrected_max"]),
            "layered_core_header_rs_fail_count": float(core_debug["rs_fail_count"]),
            "layered_core_header_crc_fail_count": float(core_debug["crc_fail_count"]),
            "layered_core_header_fail_examples": list(core_debug["fail_examples"]),
            "layered_bootstrap_attempt_count": float(core_debug["attempt_count"]),
            "layered_bootstrap_threshold_avg": float(core_debug["threshold_avg"]),
            "layered_bootstrap_vote_margin_min": float(core_debug["vote_margin_min"]),
            "layered_bootstrap_vote_margin_avg": float(core_debug["vote_margin_avg"]),
            "layered_bootstrap_template_best_score_avg": float(core_debug["template_best_score_avg"]),
            "layered_bootstrap_template_best_score_min": float(core_debug["template_best_score_min"]),
            "layered_bootstrap_template_margin_avg": float(core_debug["template_margin_avg"]),
            "layered_bootstrap_template_margin_min": float(core_debug["template_margin_min"]),
            "layered_bootstrap_bit_fail_counts": list(self.bootstrap_bit_fail_counts),
            "layered_bootstrap_fail_examples": list(self.bootstrap_fail_examples),
            "layered_bootstrap_rs_fail_count": float(self.bootstrap_rs_fail_count),
            "layered_bootstrap_crc_fail_count": float(self.bootstrap_crc_fail_count),
            "layered_control_reference_decode_mode": self.control_reference_decode_mode,
            "layered_body_rs_fail_count": float(self.body_rs_fail_count),
            "layered_body_crc_fail_count": float(self.body_crc_fail_count),
            "layered_body_profile_id": float(self.body_profile_id),
            "layered_body_ecc_profile_id": float(self.body_ecc_profile_id),
            "layered_control_prefix_fail_count": 0.0,
            "layered_format_fail_count": 0.0,
            "protocol_debug": {"layered_debug": layered_debug},
        }


def make_protocol_report_adapter(protocol: str) -> ProtocolReportAdapter:
    if protocol == "gray4":
        return Gray4ReportAdapter()
    if protocol == "layered":
        return LayeredReportAdapter()
    return NoOpProtocolReportAdapter()
