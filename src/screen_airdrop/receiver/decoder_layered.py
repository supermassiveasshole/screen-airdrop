# pyright: reportArgumentType=false
"""Layered protocol decoder."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from screen_airdrop.common.ecc_rs import (
    LAYERED_BOOTSTRAP_RS,
    ReedSolomonError,
    decode_rs_bytes,
    decode_rs_bytes_with_erasures,
    rs_encoded_size,
)
from screen_airdrop.common.protocol_basic import (
    FRAME_END,
    FRAME_SYNC,
    FrameHeaderBasic,
    validate_payload_crc,
)
from screen_airdrop.common.protocol_gray4 import decode_gray4_symbols
from screen_airdrop.common.protocol_layered import (
    BODY_META_STRUCT,
    BODY_TRAILER_SIZE,
    LAYERED_CONTROL_CELL_TEMPLATES,
    LAYERED_CONTROL_PATH_VERSION,
    LAYERED_CONTROL_SYMBOL_BITS,
    BootstrapFields,
    decode_body_raw_bytes,
    layered_body_ecc_profile,
    layered_body_profile_name,
)
from screen_airdrop.receiver.decoder_gray4 import (
    _quantize_gray4_adaptive,
    _run_locator_compact,
    _sample_gray4_modules,
    _sync_calibration_centers,
)
from screen_airdrop.receiver.locator.basic import LocatorConfig
from screen_airdrop.sender.encoder_gray4 import _mask_bit
from screen_airdrop.sender.encoder_layered import LayeredLayout, build_layout_layered


@dataclass
class DecodeMetaLayered:
    protocol_version_used: int
    locator_engine: str
    confidence: float
    fail_reason: str
    elapsed_ms: float
    legacy_used: bool
    homography_rmse: float
    rs_corrected_symbols: int
    crc_ok: bool
    mask_id: int
    body_profile_id: int
    body_profile_name: str
    grid_size: str
    det_bbox: tuple[int, int, int, int]
    decode_attempts: int
    det_confidence: float
    new_fail_reason: str
    new_elapsed_ms: float
    legacy_elapsed_ms: float
    locator_debug_artifacts: Dict[str, object]
    locator_warped_preview: Optional[np.ndarray]
    avg_symbol_confidence: float
    total_decode_ms: float = 0.0
    calibration_centers: Optional[Tuple[float, float, float, float]] = None
    bootstrap_attempt_count: int = 0
    bootstrap_threshold: int = 0
    bootstrap_vote_margin_min: float = 0.0
    bootstrap_vote_margin_avg: float = 0.0
    bootstrap_erasure_symbol_count: int = 0
    control_band_decode_stage: str = ""
    control_trace: Dict[str, Any] = field(default_factory=dict)
    quad_src: Optional[np.ndarray] = None
    homography: Optional[np.ndarray] = None
    homography_inv: Optional[np.ndarray] = None
    geometry_reused: bool = False


@dataclass(frozen=True)
class LayeredGeometryState:
    quad_src: np.ndarray
    homography: np.ndarray
    homography_inv: np.ndarray
    grid_bbox_std: tuple[int, int, int, int]
    warped_shape: tuple[int, int]
    locator_engine: str
    det_confidence: float
    homography_rmse: float


class LayeredDecodeTraceError(ValueError):
    def __init__(self, detail: str, trace: Optional[Dict[str, Any]] = None):
        super().__init__(detail)
        self.detail = detail
        self.trace = trace or {}


def _bytes_from_dibits(dibits: List[int]) -> bytes:
    out = bytearray()
    valid = (len(dibits) // 4) * 4
    for i in range(0, valid, 4):
        value = 0
        for dibit in dibits[i : i + 4]:
            value = (value << LAYERED_CONTROL_SYMBOL_BITS) | (int(dibit) & 0x03)
        out.append(value)
    return bytes(out)


def _control_cell_samples(avg_gray_u8: np.ndarray, cells: List[List[Tuple[int, int]]]) -> List[List[int]]:
    values: List[List[int]] = []
    for cell in cells:
        values.append([int(avg_gray_u8[y, x]) for x, y in cell])
    return values


def _control_reference_levels(
    avg_gray_u8: np.ndarray,
    layout: LayeredLayout,
) -> tuple[float, float, str, float]:
    samples = _control_cell_samples(avg_gray_u8, layout.bootstrap_reference_cells)
    dark_values: List[int] = []
    light_values: List[int] = []
    for idx, cell_samples in enumerate(samples):
        template = LAYERED_CONTROL_CELL_TEMPLATES[idx % len(LAYERED_CONTROL_CELL_TEMPLATES)]
        for sample, bit in zip(cell_samples, template):
            if bit:
                light_values.append(int(sample))
            else:
                dark_values.append(int(sample))
    if dark_values and light_values:
        dark_mean = float(sum(dark_values) / len(dark_values))
        light_mean = float(sum(light_values) / len(light_values))
        return dark_mean, light_mean, "reference_templates", float(light_mean - dark_mean)
    return 0.0, 255.0, "reference_default_anchors", 255.0


def _control_template_match(
    cell_samples: List[int],
    dark_level: float,
    light_level: float,
) -> tuple[int, float, float]:
    scores: List[float] = []
    for template in LAYERED_CONTROL_CELL_TEMPLATES:
        expected = [light_level if bit else dark_level for bit in template]
        score = float(
            sum(abs(float(sample) - float(expect)) for sample, expect in zip(cell_samples, expected))
            / float(max(1, len(expected)))
        )
        scores.append(score)
    ranked = sorted(enumerate(scores), key=lambda item: item[1])
    best_symbol, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else best_score
    return int(best_symbol), float(best_score), float(second_score - best_score)


def _decode_bootstrap_dibits(
    avg_gray_u8: np.ndarray,
    layout: LayeredLayout,
    *,
    dark_level: float,
    light_level: float,
) -> tuple[bytes, List[int], List[float], List[float]]:
    samples = _control_cell_samples(avg_gray_u8, layout.bootstrap_cells)
    dibits: List[int] = []
    best_scores: List[float] = []
    confidence_margins: List[float] = []
    for cell_samples in samples:
        dibit, best_score, confidence_margin = _control_template_match(
            cell_samples,
            dark_level,
            light_level,
        )
        dibits.append(dibit)
        best_scores.append(best_score)
        confidence_margins.append(confidence_margin)
    return _bytes_from_dibits(dibits), dibits, best_scores, confidence_margins


def _analyze_bootstrap_attempt(
    avg_gray_u8: np.ndarray,
    layout: LayeredLayout,
    *,
    reference_mode: str,
    dark_level: float,
    light_level: float,
    reference_contrast: float,
) -> Dict[str, Any]:
    samples = _control_cell_samples(avg_gray_u8, layout.bootstrap_cells)
    raw_bytes, dibits, best_scores, confidence_margins = _decode_bootstrap_dibits(
        avg_gray_u8,
        layout,
        dark_level=dark_level,
        light_level=light_level,
    )
    low_conf_threshold = max(4.0, float(reference_contrast) * 0.08)
    erasure_positions: List[int] = []
    if dibits:
        symbol_count = len(dibits) // 4
        for symbol_index in range(symbol_count):
            margins = confidence_margins[symbol_index * 4 : (symbol_index + 1) * 4]
            low_conf = sum(1 for margin in margins if float(margin) <= low_conf_threshold)
            if low_conf >= 1:
                erasure_positions.append(symbol_index)
    try:
        if erasure_positions:
            bootstrap_raw, _ = decode_rs_bytes_with_erasures(
                LAYERED_BOOTSTRAP_RS,
                raw_bytes,
                erasure_positions,
            )
        else:
            bootstrap_raw, _ = decode_rs_bytes(LAYERED_BOOTSTRAP_RS, raw_bytes)
        bootstrap = BootstrapFields.unpack(bootstrap_raw)
        guessed_fields: Dict[str, Any] = {
            "frame_type": int(bootstrap.frame_type),
            "body_mask_id": int(bootstrap.body_mask_id),
            "plausible": True,
        }
    except Exception:
        guessed_fields = {"plausible": False}
    return {
        "reference_mode": str(reference_mode),
        "reference_dark_level": float(dark_level),
        "reference_light_level": float(light_level),
        "reference_contrast": float(reference_contrast),
        "sample_values": samples,
        "samples_min": int(min(min(v) for v in samples) if samples else 0),
        "samples_max": int(max(max(v) for v in samples) if samples else 0),
        "samples_mean": float(
            sum(sum(v) for v in samples) / float(max(1, sum(len(v) for v in samples)))
        ),
        "binary_bits": [],
        "dibits": dibits,
        "raw_bytes_hex": raw_bytes.hex(),
        "vote_margins": confidence_margins,
        "vote_margin_min": float(min(confidence_margins) if confidence_margins else 0.0),
        "vote_margin_avg": float(sum(confidence_margins) / float(max(1, len(confidence_margins)))),
        "template_best_score_min": float(min(best_scores) if best_scores else 0.0),
        "template_best_score_avg": float(sum(best_scores) / float(max(1, len(best_scores)))),
        "template_margin_min": float(min(confidence_margins) if confidence_margins else 0.0),
        "template_margin_avg": float(sum(confidence_margins) / float(max(1, len(confidence_margins)))),
        "erasure_symbol_positions": erasure_positions,
        "erasure_symbol_count": len(erasure_positions),
        "low_conf_threshold": float(low_conf_threshold),
        "guessed_fields": guessed_fields,
    }


def _decode_bootstrap_control_band(
    avg_gray_u8: np.ndarray,
    layout: LayeredLayout,
    calibration_by_mask: Optional[Dict[int, np.ndarray]],
) -> tuple[BootstrapFields, int, Dict[str, Any]]:
    del calibration_by_mask
    attempts: List[Dict[str, Any]] = []
    last_error = "bootstrap rs decode failed"
    bootstrap_rs_corrected = 0
    dark_level, light_level, reference_mode, reference_contrast = _control_reference_levels(avg_gray_u8, layout)
    if reference_contrast < 12.0:
        trace = {
            "control_path_version": int(LAYERED_CONTROL_PATH_VERSION),
            "bootstrap_attempt_count": 1,
            "control_reference_decode_mode": str(reference_mode),
            "control_band_decode_stage": "bootstrap_template_match",
            "attempts": [
                {
                    "reference_mode": str(reference_mode),
                    "reference_dark_level": float(dark_level),
                    "reference_light_level": float(light_level),
                    "reference_contrast": float(reference_contrast),
                    "status": "bootstrap_template_match_failed",
                    "decode_stage": "bootstrap_template_match",
                }
            ],
        }
        raise LayeredDecodeTraceError("bootstrap template match failed", trace=trace)
    analysis = _analyze_bootstrap_attempt(
        avg_gray_u8,
        layout,
        reference_mode=reference_mode,
        dark_level=dark_level,
        light_level=light_level,
        reference_contrast=reference_contrast,
    )
    bootstrap_bytes = bytes.fromhex(str(analysis["raw_bytes_hex"]))
    try:
        if analysis["erasure_symbol_positions"]:
            bootstrap_raw, bootstrap_rs_corrected = decode_rs_bytes_with_erasures(
                LAYERED_BOOTSTRAP_RS,
                bootstrap_bytes,
                [int(pos) for pos in analysis["erasure_symbol_positions"]],
            )
        else:
            bootstrap_raw, bootstrap_rs_corrected = decode_rs_bytes(LAYERED_BOOTSTRAP_RS, bootstrap_bytes)
    except ReedSolomonError:
        analysis["status"] = "bootstrap_rs_failed"
        analysis["decode_stage"] = "bootstrap_rs"
        attempts.append(analysis)
        last_error = "bootstrap rs decode failed"
    else:
        try:
            bootstrap = BootstrapFields.unpack(bootstrap_raw)
        except ValueError as exc:
            analysis["status"] = "bootstrap_crc_failed"
            analysis["decode_stage"] = "bootstrap_crc"
            attempts.append(analysis)
            last_error = "bootstrap crc mismatch" if "crc" in str(exc).lower() else str(exc)
        else:
            analysis["status"] = "ok"
            analysis["decode_stage"] = "ok"
            attempts.append(analysis)
            return bootstrap, int(bootstrap_rs_corrected), {
                "control_path_version": int(LAYERED_CONTROL_PATH_VERSION),
                "bootstrap_attempt_count": len(attempts),
                "bootstrap_threshold": 0,
                "bootstrap_vote_margin_min": float(analysis["vote_margin_min"]),
                "bootstrap_vote_margin_avg": float(analysis["vote_margin_avg"]),
                "bootstrap_erasure_symbol_count": int(analysis["erasure_symbol_count"]),
                "bootstrap_template_best_score_min": float(analysis["template_best_score_min"]),
                "bootstrap_template_best_score_avg": float(analysis["template_best_score_avg"]),
                "bootstrap_template_margin_min": float(analysis["template_margin_min"]),
                "bootstrap_template_margin_avg": float(analysis["template_margin_avg"]),
                "control_reference_decode_mode": str(reference_mode),
                "control_band_decode_stage": "ok",
                "attempts": attempts,
                "bootstrap_rs_corrected": int(bootstrap_rs_corrected),
            }
    raise LayeredDecodeTraceError(
        last_error,
        trace={
            "control_path_version": int(LAYERED_CONTROL_PATH_VERSION),
            "bootstrap_attempt_count": len(attempts),
            "control_reference_decode_mode": str(reference_mode),
            "control_band_decode_stage": attempts[-1]["decode_stage"] if attempts else "bootstrap_rs",
            "attempts": attempts,
        },
    )


def _body_symbols_from_modules(
    avg_gray_u8: np.ndarray,
    layout: LayeredLayout,
    centers: np.ndarray,
    mask_id: int,
) -> tuple[List[int], float]:
    symbols: List[int] = []
    confidences: List[float] = []
    for x, y in layout.body_coords:
        sym, conf = _quantize_gray4_adaptive(int(avg_gray_u8[y, x]), centers)
        if _mask_bit(mask_id, x, y):
            sym ^= 0x03
        symbols.append(sym)
        confidences.append(conf)
    return symbols, (float(sum(confidences)) / float(max(1, len(confidences))))


def _decode_body(
    avg_gray_u8: np.ndarray,
    layout: LayeredLayout,
    bootstrap: BootstrapFields,
    calibration_by_mask: Optional[Dict[int, np.ndarray]],
) -> tuple[FrameHeaderBasic, bytes, int, float]:
    body_rs = layered_body_ecc_profile(int(bootstrap.body_profile_id))
    values = np.array([float(avg_gray_u8[y, x]) for x, y in layout.body_coords], dtype=np.float32)
    candidate_centers: List[np.ndarray] = [np.array([0.0, 85.0, 170.0, 255.0], dtype=np.float32)]
    if calibration_by_mask is not None:
        cached = calibration_by_mask.get(int(bootstrap.body_mask_id))
        if cached is not None:
            candidate_centers.append(np.asarray(cached, dtype=np.float32))
    if values.size >= 16:
        candidate_centers.append(
            np.array(
                [
                    float(np.percentile(values, 1.0)),
                    float(np.percentile(values, 35.0)),
                    float(np.percentile(values, 65.0)),
                    float(np.percentile(values, 99.0)),
                ],
                dtype=np.float32,
            )
        )

    last_rs_error: Optional[Exception] = None
    last_crc_error: Optional[Exception] = None
    rs_corrected = 0
    avg_conf = 0.0
    for centers in candidate_centers:
        body_symbols, avg_conf = _body_symbols_from_modules(
            avg_gray_u8,
            layout,
            np.asarray(centers, dtype=np.float32),
            int(bootstrap.body_mask_id),
        )
        body_coded_len = rs_encoded_size(body_rs, BODY_META_STRUCT.size + BODY_TRAILER_SIZE + int(bootstrap.payload_len))
        coded_bytes = decode_gray4_symbols(body_symbols, int(body_coded_len))
        try:
            raw_body, rs_corrected = decode_rs_bytes(body_rs, coded_bytes)
        except ReedSolomonError as exc:
            last_rs_error = exc
            continue
        try:
            meta, payload = decode_body_raw_bytes(raw_body, int(bootstrap.payload_len))
            validate_payload_crc(meta.payload_crc32, payload)
        except ValueError as exc:
            last_crc_error = exc
            continue
        header = FrameHeaderBasic.make(
            frame_type=int(bootstrap.frame_type),
            session_id=int(bootstrap.short_session_tag),
            epoch_id=int(meta.epoch_id),
            frame_id=int(meta.frame_id),
            total_frames=int(meta.total_frames),
            chunk_id=int(meta.chunk_id),
            payload=payload,
            flags=0,
        )
        return header, payload, int(rs_corrected), float(avg_conf)

    if last_crc_error is not None:
        raise LayeredDecodeTraceError("body crc mismatch", trace={"control_band_decode_stage": "body_crc"})
    raise LayeredDecodeTraceError("body RS decode failed", trace={"control_band_decode_stage": "body_rs"}) from last_rs_error


def _decode_layered_from_warped(
    *,
    warped: np.ndarray,
    layout: LayeredLayout,
    geometry: LayeredGeometryState,
    calibration_by_mask: Optional[Dict[int, np.ndarray]],
    elapsed_ms: float,
    locator_debug_artifacts: Optional[Dict[str, Any]] = None,
    geometry_reused: bool = False,
) -> tuple[FrameHeaderBasic, bytes, DecodeMetaLayered]:
    sample_stack_u8, avg_gray_u8, header_modules, fixed_modules, adaptive_modules, confidences = _sample_gray4_modules(
        warped, layout.base
    )
    _ = sample_stack_u8, header_modules, fixed_modules, adaptive_modules, confidences

    bootstrap, bootstrap_rs_corrected, control_trace = _decode_bootstrap_control_band(
        avg_gray_u8,
        layout,
        calibration_by_mask,
    )

    calibration_centers = None
    payload = b""
    rs_corrected = int(bootstrap_rs_corrected)
    avg_conf = 1.0
    decode_stage = "bootstrap_rs"
    if int(bootstrap.frame_type) == FRAME_SYNC:
        centers = _sync_calibration_centers(avg_gray_u8, layout.base, 0)
        if centers is not None and calibration_by_mask is not None:
            calibration_by_mask[int(bootstrap.body_mask_id)] = centers.astype(np.float32)
            calibration_centers = tuple(float(v) for v in centers)
        header = FrameHeaderBasic.make(
            frame_type=FRAME_SYNC,
            session_id=int(bootstrap.short_session_tag),
            epoch_id=0,
            frame_id=0,
            total_frames=0,
            chunk_id=0,
            payload=b"",
            flags=0,
        )
    elif int(bootstrap.frame_type) == FRAME_END:
        header = FrameHeaderBasic.make(
            frame_type=FRAME_END,
            session_id=int(bootstrap.short_session_tag),
            epoch_id=0,
            frame_id=0,
            total_frames=0,
            chunk_id=0,
            payload=b"",
            flags=0,
        )
    else:
        decode_stage = "body"
        header, payload, body_rs_corrected, avg_conf = _decode_body(
            avg_gray_u8,
            layout,
            bootstrap,
            calibration_by_mask,
        )
        rs_corrected += int(body_rs_corrected)

    meta = DecodeMetaLayered(
        protocol_version_used=52,
        locator_engine=str(geometry.locator_engine),
        confidence=float(avg_conf),
        fail_reason="",
        elapsed_ms=float(elapsed_ms),
        legacy_used=False,
        homography_rmse=float(geometry.homography_rmse),
        rs_corrected_symbols=int(rs_corrected),
        crc_ok=True,
        mask_id=int(bootstrap.body_mask_id),
        body_profile_id=int(bootstrap.body_profile_id),
        body_profile_name=layered_body_profile_name(int(bootstrap.body_profile_id)),
        grid_size=f"{layout.base.grid_w}x{layout.base.grid_h}",
        det_bbox=tuple(int(v) for v in geometry.grid_bbox_std),
        decode_attempts=1,
        det_confidence=float(geometry.det_confidence),
        new_fail_reason="",
        new_elapsed_ms=0.0,
        legacy_elapsed_ms=0.0,
        locator_debug_artifacts=dict(locator_debug_artifacts or {}),
        locator_warped_preview=warped.copy(),
        avg_symbol_confidence=float(avg_conf),
        total_decode_ms=float(elapsed_ms),
        calibration_centers=calibration_centers,
        bootstrap_attempt_count=int(control_trace.get("bootstrap_attempt_count", 0)),
        bootstrap_threshold=int(control_trace.get("bootstrap_threshold", 0)),
        bootstrap_vote_margin_min=float(control_trace.get("bootstrap_vote_margin_min", 0.0)),
        bootstrap_vote_margin_avg=float(control_trace.get("bootstrap_vote_margin_avg", 0.0)),
        bootstrap_erasure_symbol_count=int(control_trace.get("bootstrap_erasure_symbol_count", 0)),
        control_band_decode_stage=str(control_trace.get("control_band_decode_stage", decode_stage)),
        control_trace=dict(control_trace),
        quad_src=np.array(geometry.quad_src, copy=True),
        homography=np.array(geometry.homography, copy=True),
        homography_inv=np.array(geometry.homography_inv, copy=True),
        geometry_reused=bool(geometry_reused),
    )
    return header, payload, meta


def decode_frame_layered(
    frame: np.ndarray,
    detect_mode: str = "full",
    forced_roi: Optional[Tuple[int, int, int, int]] = None,
    grid_w: int = 224,
    grid_h: int = 136,
    guard_band: int = 1,
    corner_size: int = 7,
    roi_only: bool = False,
    manual_strict: bool = False,
    locator_engine: str = "auto",
    locator_confidence_threshold: float = 0.55,
    calibration_by_mask: Optional[Dict[int, np.ndarray]] = None,
) -> tuple[FrameHeaderBasic, bytes, DecodeMetaLayered]:
    t0 = time.perf_counter()
    if detect_mode not in ("full", "track", "roi"):
        raise ValueError("invalid detect_mode")
    if locator_engine not in ("new", "legacy", "auto"):
        raise ValueError("invalid locator_engine")
    if manual_strict or roi_only:
        if forced_roi is None:
            raise ValueError("manual_strict/roi_only requires forced_roi")
        search_roi = forced_roi
    elif detect_mode == "full":
        search_roi = None
    else:
        search_roi = forced_roi

    cfg = LocatorConfig(
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=guard_band,
        corner_size=corner_size,
        confidence_threshold=locator_confidence_threshold,
    )
    layout = build_layout_layered(grid_w, grid_h, guard_band, corner_size)
    loc, used_engine, new_err, _legacy_err = _run_locator_compact(
        frame=frame,
        locator_engine=locator_engine,
        search_roi=search_roi,
        cfg=cfg,
    )
    geometry = LayeredGeometryState(
        quad_src=np.array(loc.quad_src, copy=True),
        homography=np.array(loc.homography, copy=True),
        homography_inv=np.array(loc.homography_inv, copy=True),
        grid_bbox_std=tuple(int(v) for v in loc.grid_bbox_std),
        warped_shape=(int(loc.warped.shape[1]), int(loc.warped.shape[0])),
        locator_engine=str(used_engine),
        det_confidence=float(loc.quality.confidence),
        homography_rmse=float(loc.quality.warp_rmse),
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return _decode_layered_from_warped(
        warped=loc.warped,
        layout=layout,
        geometry=geometry,
        calibration_by_mask=calibration_by_mask,
        elapsed_ms=float(elapsed_ms),
        locator_debug_artifacts={
            "new_fail_reason": str(new_err or ""),
            "grid_bbox_std": [int(v) for v in loc.grid_bbox_std],
        },
        geometry_reused=False,
    )


def locate_geometry_layered(
    frame: np.ndarray,
    detect_mode: str = "full",
    forced_roi: Optional[Tuple[int, int, int, int]] = None,
    grid_w: int = 224,
    grid_h: int = 136,
    guard_band: int = 1,
    corner_size: int = 7,
    roi_only: bool = False,
    manual_strict: bool = False,
    locator_engine: str = "auto",
    locator_confidence_threshold: float = 0.55,
) -> LayeredGeometryState:
    """Locate layered geometry without completing a full frame decode."""
    if detect_mode not in ("full", "track", "roi"):
        raise ValueError("invalid detect_mode")
    if locator_engine not in ("new", "legacy", "auto"):
        raise ValueError("invalid locator_engine")
    if manual_strict or roi_only:
        if forced_roi is None:
            raise ValueError("manual_strict/roi_only requires forced_roi")
        search_roi = forced_roi
    elif detect_mode == "full":
        search_roi = None
    else:
        search_roi = forced_roi

    cfg = LocatorConfig(
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=guard_band,
        corner_size=corner_size,
        confidence_threshold=locator_confidence_threshold,
    )
    loc, used_engine, _new_err, _legacy_err = _run_locator_compact(
        frame=frame,
        locator_engine=locator_engine,
        search_roi=search_roi,
        cfg=cfg,
    )
    return LayeredGeometryState(
        quad_src=np.array(loc.quad_src, copy=True),
        homography=np.array(loc.homography, copy=True),
        homography_inv=np.array(loc.homography_inv, copy=True),
        grid_bbox_std=tuple(int(v) for v in loc.grid_bbox_std),
        warped_shape=(int(loc.warped.shape[1]), int(loc.warped.shape[0])),
        locator_engine=str(used_engine),
        det_confidence=float(loc.quality.confidence),
        homography_rmse=float(loc.quality.warp_rmse),
    )


def decode_frame_layered_with_geometry(
    frame: np.ndarray,
    geometry: LayeredGeometryState,
    *,
    grid_w: int = 224,
    grid_h: int = 136,
    guard_band: int = 1,
    corner_size: int = 7,
    calibration_by_mask: Optional[Dict[int, np.ndarray]] = None,
) -> tuple[FrameHeaderBasic, bytes, DecodeMetaLayered]:
    t0 = time.perf_counter()
    layout = build_layout_layered(grid_w, grid_h, guard_band, corner_size)
    warp_w, warp_h = geometry.warped_shape
    warped = cv2.warpPerspective(
        frame,
        np.asarray(geometry.homography, dtype=np.float32),
        (int(warp_w), int(warp_h)),
        flags=cv2.INTER_LINEAR,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return _decode_layered_from_warped(
        warped=warped,
        layout=layout,
        geometry=geometry,
        calibration_by_mask=calibration_by_mask,
        elapsed_ms=float(elapsed_ms),
        locator_debug_artifacts={"geometry_reused": True},
        geometry_reused=True,
    )


def probe_geometry_layered(
    frame: np.ndarray,
    geometry: LayeredGeometryState,
    *,
    grid_w: int = 224,
    grid_h: int = 136,
    guard_band: int = 1,
    corner_size: int = 7,
    calibration_by_mask: Optional[Dict[int, np.ndarray]] = None,
) -> Dict[str, Any]:
    """Probe layered control-band health for a candidate geometry."""
    layout = build_layout_layered(grid_w, grid_h, guard_band, corner_size)
    warp_w, warp_h = geometry.warped_shape
    warped = cv2.warpPerspective(
        frame,
        np.asarray(geometry.homography, dtype=np.float32),
        (int(warp_w), int(warp_h)),
        flags=cv2.INTER_LINEAR,
    )
    _sample_stack_u8, avg_gray_u8, _header_modules, _fixed_modules, _adaptive_modules, _confidences = (
        _sample_gray4_modules(warped, layout.base)
    )
    try:
        _bootstrap, _rs_corrected, control_trace = _decode_bootstrap_control_band(
            avg_gray_u8,
            layout,
            calibration_by_mask,
        )
        attempts = control_trace.get("attempts")
        last_attempt = attempts[-1] if isinstance(attempts, list) and attempts else {}
        stage = str(control_trace.get("control_band_decode_stage", "ok") or "ok")
        return {
            "reference_contrast": float(last_attempt.get("reference_contrast", 0.0) or 0.0),
            "template_margin_min": float(last_attempt.get("template_margin_min", 0.0) or 0.0),
            "template_margin_avg": float(last_attempt.get("template_margin_avg", 0.0) or 0.0),
            "bootstrap_ok": True,
            "bootstrap_failure_stage": "" if stage == "ok" else stage,
        }
    except LayeredDecodeTraceError as exc:
        trace = exc.trace if isinstance(exc.trace, dict) else {}
        attempts = trace.get("attempts")
        last_attempt = attempts[-1] if isinstance(attempts, list) and attempts else {}
        stage = str(trace.get("control_band_decode_stage", "") or "")
        return {
            "reference_contrast": float(last_attempt.get("reference_contrast", 0.0) or 0.0),
            "template_margin_min": float(last_attempt.get("template_margin_min", 0.0) or 0.0),
            "template_margin_avg": float(last_attempt.get("template_margin_avg", 0.0) or 0.0),
            "bootstrap_ok": False,
            "bootstrap_failure_stage": stage,
        }
