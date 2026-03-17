# pyright: reportArgumentType=false
"""Layered protocol decoder."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from screen_airdrop.common.ecc_rs import (
    LAYERED_BODY_RS,
    LAYERED_BOOTSTRAP_RS,
    ReedSolomonError,
    decode_rs_bytes,
    decode_rs_bytes_with_erasures,
)
from screen_airdrop.common.protocol_basic import (
    FRAME_END,
    FRAME_SYNC,
    FrameHeaderBasic,
    validate_payload_crc,
)
from screen_airdrop.common.protocol_gray4 import decode_gray4_symbols
from screen_airdrop.common.protocol_layered import (
    LAYERED_CONTROL_PATH_VERSION,
    BootstrapFields,
    decode_body_raw_bytes,
)
from screen_airdrop.receiver.decoder_gray4 import (
    _binary_threshold_from_centers,
    _quantize_gray4_adaptive,
    _run_locator_compact,
    _sample_gray4_modules,
    _sync_calibration_centers,
)
from screen_airdrop.receiver.locator_basic import LocatorConfig
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


def _bytes_from_bits(bits: List[int]) -> bytes:
    out = bytearray()
    valid = (len(bits) // 8) * 8
    for i in range(0, valid, 8):
        value = 0
        for bit in bits[i : i + 8]:
            value = (value << 1) | (int(bit) & 1)
        out.append(value)
    return bytes(out)


def _control_cell_values(avg_gray_u8: np.ndarray, cells: List[List[Tuple[int, int]]]) -> List[int]:
    values: List[int] = []
    for cell in cells:
        values.append(int(round(sum(int(avg_gray_u8[y, x]) for x, y in cell) / float(len(cell)))))
    return values


def _control_band_thresholds(
    avg_gray_u8: np.ndarray,
    layout: LayeredLayout,
    calibration_by_mask: Optional[Dict[int, np.ndarray]],
) -> List[Tuple[str, int]]:
    values = _control_cell_values(avg_gray_u8, layout.control_cells)
    ref_values = _control_cell_values(avg_gray_u8, layout.bootstrap_reference_cells)
    if ref_values:
        dark = [value for idx, value in enumerate(ref_values) if idx % 2 == 0]
        light = [value for idx, value in enumerate(ref_values) if idx % 2 == 1]
        if dark and light:
            reference_threshold = int(round((float(sum(dark)) / len(dark) + float(sum(light)) / len(light)) * 0.5))
            out: List[Tuple[str, int]] = [("control_band_reference_midpoint", reference_threshold)]
        else:
            minmax_threshold = (min(values) + max(values)) // 2 if values else 128
            out = [("control_band_minmax", int(minmax_threshold))]
    else:
        minmax_threshold = (min(values) + max(values)) // 2 if values else 128
        out = [("control_band_minmax", int(minmax_threshold))]
    if calibration_by_mask:
        stacked = np.stack([np.asarray(v, dtype=np.float32) for v in calibration_by_mask.values()], axis=0)
        centers = np.mean(stacked, axis=0)
        calibration_threshold = int(_binary_threshold_from_centers(np.asarray(centers, dtype=np.float32)))
        if calibration_threshold not in {threshold for _, threshold in out}:
            out.append(("control_band_calibration_midpoint", calibration_threshold))
    return out


def _decode_bootstrap_bits(
    avg_gray_u8: np.ndarray,
    layout: LayeredLayout,
    threshold: int,
) -> bytes:
    values = _control_cell_values(avg_gray_u8, layout.bootstrap_cells)
    bits = [1 if value >= int(threshold) else 0 for value in values]
    return _bytes_from_bits(bits)


def _analyze_bootstrap_attempt(
    avg_gray_u8: np.ndarray,
    layout: LayeredLayout,
    *,
    threshold_mode: str,
    threshold_value: int,
) -> Dict[str, Any]:
    values = _control_cell_values(avg_gray_u8, layout.bootstrap_cells)
    bits = [1 if value >= int(threshold_value) else 0 for value in values]
    raw_bytes = _bytes_from_bits(bits)
    vote_margins = [abs(int(value) - int(threshold_value)) for value in values]
    contrast_span = max(0, int(max(values) - min(values))) if values else 0
    low_conf_threshold = max(8, int(round(contrast_span * 0.12)))
    erasure_positions: List[int] = []
    if bits:
        symbol_count = len(bits) // 8
        for symbol_index in range(symbol_count):
            margins = vote_margins[symbol_index * 8 : (symbol_index + 1) * 8]
            low_conf = sum(1 for margin in margins if int(margin) <= low_conf_threshold)
            if low_conf >= 2:
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
        "threshold_mode": str(threshold_mode),
        "threshold_value": int(threshold_value),
        "sample_values": values,
        "samples_min": int(min(values) if values else 0),
        "samples_max": int(max(values) if values else 0),
        "samples_mean": float(sum(values) / float(max(1, len(values)))),
        "binary_bits": bits,
        "raw_bytes_hex": raw_bytes.hex(),
        "vote_margins": vote_margins,
        "vote_margin_min": float(min(vote_margins) if vote_margins else 0.0),
        "vote_margin_avg": float(sum(vote_margins) / float(max(1, len(vote_margins)))),
        "erasure_symbol_positions": erasure_positions,
        "erasure_symbol_count": len(erasure_positions),
        "low_conf_threshold": int(low_conf_threshold),
        "guessed_fields": guessed_fields,
    }


def _decode_bootstrap_control_band(
    avg_gray_u8: np.ndarray,
    layout: LayeredLayout,
    calibration_by_mask: Optional[Dict[int, np.ndarray]],
) -> tuple[BootstrapFields, int, Dict[str, Any]]:
    attempts: List[Dict[str, Any]] = []
    last_error = "bootstrap rs decode failed"
    bootstrap_rs_corrected = 0
    for attempt_name, threshold in _control_band_thresholds(avg_gray_u8, layout, calibration_by_mask):
        analysis = _analyze_bootstrap_attempt(
            avg_gray_u8,
            layout,
            threshold_mode=attempt_name,
            threshold_value=int(threshold),
        )
        bootstrap_bytes = _decode_bootstrap_bits(avg_gray_u8, layout, int(threshold))
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
            continue
        try:
            bootstrap = BootstrapFields.unpack(bootstrap_raw)
        except ValueError as exc:
            analysis["status"] = "bootstrap_crc_failed"
            analysis["decode_stage"] = "bootstrap_crc"
            attempts.append(analysis)
            last_error = "bootstrap crc mismatch" if "crc" in str(exc).lower() else str(exc)
            continue
        analysis["status"] = "ok"
        analysis["decode_stage"] = "ok"
        attempts.append(analysis)
        return bootstrap, int(bootstrap_rs_corrected), {
            "control_path_version": int(LAYERED_CONTROL_PATH_VERSION),
            "bootstrap_attempt_count": len(attempts),
            "bootstrap_threshold": int(threshold),
            "bootstrap_vote_margin_min": float(analysis["vote_margin_min"]),
            "bootstrap_vote_margin_avg": float(analysis["vote_margin_avg"]),
            "bootstrap_erasure_symbol_count": int(analysis["erasure_symbol_count"]),
            "control_band_decode_stage": "ok",
            "attempts": attempts,
            "bootstrap_rs_corrected": int(bootstrap_rs_corrected),
        }
    raise LayeredDecodeTraceError(
        last_error,
        trace={
            "control_path_version": int(LAYERED_CONTROL_PATH_VERSION),
            "bootstrap_attempt_count": len(attempts),
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
        coded_bytes = decode_gray4_symbols(body_symbols, int(bootstrap.body_coded_len))
        try:
            raw_body, rs_corrected = decode_rs_bytes(LAYERED_BODY_RS, coded_bytes)
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
            session_id=int(bootstrap.session_id),
            epoch_id=int(bootstrap.epoch_id),
            frame_id=int(bootstrap.frame_id),
            total_frames=int(meta.total_frames),
            chunk_id=int(meta.chunk_id),
            payload=payload,
            flags=0,
        )
        return header, payload, int(rs_corrected), float(avg_conf)

    if last_crc_error is not None:
        raise LayeredDecodeTraceError("payload crc mismatch", trace={"control_band_decode_stage": "body_crc"})
    raise LayeredDecodeTraceError("payload rs decode failed", trace={"control_band_decode_stage": "body_rs"}) from last_rs_error


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
            session_id=int(bootstrap.session_id),
            epoch_id=int(bootstrap.epoch_id),
            frame_id=int(bootstrap.frame_id),
            total_frames=0,
            chunk_id=0,
            payload=b"",
            flags=0,
        )
    elif int(bootstrap.frame_type) == FRAME_END:
        header = FrameHeaderBasic.make(
            frame_type=FRAME_END,
            session_id=int(bootstrap.session_id),
            epoch_id=int(bootstrap.epoch_id),
            frame_id=int(bootstrap.frame_id),
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
