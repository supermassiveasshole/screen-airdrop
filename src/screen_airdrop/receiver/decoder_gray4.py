"""Gray4 decoder: compact locator plus 4-level grayscale payload demodulation."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from screen_airdrop.common.layout_compact import (
    DEFAULT_FINDER_COMPACT,
    DEFAULT_GRID_H_COMPACT,
    DEFAULT_GRID_W_COMPACT,
    DEFAULT_GUARD_COMPACT,
    LayoutInfoCompact,
    LayoutInfoError,
)
from screen_airdrop.common.protocol_basic import (
    ECC_Q,
    ECC_TO_REP,
    FORMAT_SIZE,
    FRAME_SYNC,
    HEADER_SIZE,
    ID_TO_ECC,
    FormatInfoBasic,
    FrameHeaderBasic,
    validate_payload_crc,
)
from screen_airdrop.common.protocol_gray4 import (
    GRAY4_THRESHOLDS,
    decode_gray4_symbols,
    decode_repetition_symbols,
)
from screen_airdrop.receiver.control_decode import decode_binary_control_header
from screen_airdrop.receiver.decoder_compact import _run_locator as _run_locator_compact
from screen_airdrop.receiver.detector_basic import _bbox_from_non_black
from screen_airdrop.receiver.locator_basic import LocateError, LocateResult, LocatorConfig
from screen_airdrop.sender.encoder_gray4 import (
    Gray4Layout,
    build_layout_gray4,
    gray4_header_repetition,
)


def _bytes_from_bits(bits: List[int]) -> bytes:
    out = bytearray()
    for i in range(0, len(bits), 8):
        v = 0
        for b in bits[i : i + 8]:
            v = (v << 1) | (int(b) & 1)
        out.append(v)
    return bytes(out)


@dataclass
class DecodeMetaGray4:
    """Decode metadata for gray4 protocol."""
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
    avg_symbol_confidence: float  # Gray4-specific: average quantization confidence
    total_decode_ms: float = 0.0
    phase_candidates_tried: int = 0
    phase_sweep_used: bool = False
    payload_low_conf_symbols: int = 0
    payload_variant_attempts: int = 0
    calibration_centers: Optional[Tuple[float, float, float, float]] = None


def _mask_bit(mask_id: int, x: int, y: int) -> int:
    """Mask pattern (reused from basic protocol)."""
    if mask_id == 0:
        return (x + y) & 1
    if mask_id == 1:
        return y & 1
    if mask_id == 2:
        return x % 3 == 0
    if mask_id == 3:
        return (x + y) % 3 == 0
    if mask_id == 4:
        return ((y // 2) + (x // 3)) & 1
    if mask_id == 5:
        return ((x * y) % 2) + ((x * y) % 3) == 0
    if mask_id == 6:
        return (((x * y) % 2) + ((x * y) % 3)) & 1
    return (((x + y) % 2) + ((x * y) % 3)) & 1


def _quantize_gray4(avg_value: int) -> tuple[int, float]:
    """
    Quantize averaged grayscale value to 2-bit symbol with confidence.
    
    Thresholds: [43, 128, 213] (midpoints between levels 0/85/170/255)
    
    Returns:
        symbol: 0-3
        confidence: 0.0-1.0 (distance from decision boundary)
    """
    if avg_value < GRAY4_THRESHOLDS[0]:  # < 43
        symbol = 0
        # Confidence: closer to 0 is better
        conf = 1.0 - (avg_value / GRAY4_THRESHOLDS[0])
    elif avg_value < GRAY4_THRESHOLDS[1]:  # 43-127
        symbol = 1
        # Confidence: closer to 85 is better
        conf = 1.0 - abs(avg_value - 85) / 42.0
    elif avg_value < GRAY4_THRESHOLDS[2]:  # 128-212
        symbol = 2
        # Confidence: closer to 170 is better
        conf = 1.0 - abs(avg_value - 170) / 42.0
    else:  # >= 213
        symbol = 3
        # Confidence: closer to 255 is better
        conf = 1.0 - abs(255 - avg_value) / 42.0
    
    return symbol, max(0.0, min(1.0, conf))


def _fit_gray4_centers(avg_gray_u8: np.ndarray, layout: Gray4Layout) -> np.ndarray:
    """
    Estimate four grayscale centers from the current frame's payload region.

    Fixed thresholds are fragile under blur/gamma drift. We instead fit a
    lightweight 1D k-means model over sampled payload cell intensities.
    """
    values = np.array(
        [float(avg_gray_u8[y, x]) for x, y in layout.data_coords],
        dtype=np.float32,
    )
    if values.size < 16:
        return np.array([0.0, 85.0, 170.0, 255.0], dtype=np.float32)

    lo = float(np.percentile(values, 1.0))
    hi = float(np.percentile(values, 99.0))
    if hi - lo < 24.0:
        return np.array([0.0, 85.0, 170.0, 255.0], dtype=np.float32)

    centers = np.array(
        [
            lo,
            float(np.percentile(values, 35.0)),
            float(np.percentile(values, 65.0)),
            hi,
        ],
        dtype=np.float32,
    )
    centers.sort()

    for _ in range(6):
        distances = np.abs(values[:, None] - centers[None, :])
        labels = np.argmin(distances, axis=1)
        updated = centers.copy()
        for idx in range(4):
            cluster = values[labels == idx]
            if cluster.size > 0:
                updated[idx] = float(np.mean(cluster))
        updated.sort()
        if float(np.max(np.abs(updated - centers))) < 0.5:
            centers = updated
            break
        centers = updated

    centers[0] = min(centers[0], lo)
    centers[3] = max(centers[3], hi)
    for idx in range(1, 4):
        if centers[idx] <= centers[idx - 1]:
            centers[idx] = centers[idx - 1] + 1.0
    return centers


def _quantize_gray4_adaptive(avg_value: int, centers: np.ndarray) -> tuple[int, float]:
    if centers.shape != (4,):
        return _quantize_gray4(avg_value)
    thresholds = [
        0.5 * float(centers[0] + centers[1]),
        0.5 * float(centers[1] + centers[2]),
        0.5 * float(centers[2] + centers[3]),
    ]
    spacings = [
        max(1.0, thresholds[0] - float(centers[0])),
        max(1.0, min(thresholds[1] - float(centers[1]), float(centers[1]) - thresholds[0])),
        max(1.0, min(thresholds[2] - float(centers[2]), float(centers[2]) - thresholds[1])),
        max(1.0, float(centers[3]) - thresholds[2]),
    ]
    if avg_value < thresholds[0]:
        symbol = 0
    elif avg_value < thresholds[1]:
        symbol = 1
    elif avg_value < thresholds[2]:
        symbol = 2
    else:
        symbol = 3
    conf = 1.0 - (abs(float(avg_value) - float(centers[symbol])) / spacings[symbol])
    return symbol, max(0.0, min(1.0, conf))


def _binary_threshold_from_centers(centers: np.ndarray) -> int:
    if centers.shape != (4,):
        return 128
    threshold = 0.5 * float(centers[0] + centers[3])
    return int(max(1.0, min(254.0, threshold)))


def _sync_calibration_centers(
    avg_gray_u8: np.ndarray,
    layout: Gray4Layout,
    header_cell_count: int,
) -> Optional[np.ndarray]:
    payload_coords = layout.data_coords[header_cell_count:]
    if not payload_coords:
        return None
    x_mid = 0.5 * float(layout.grid_x0 + layout.grid_x1)
    y_mid = 0.5 * float(layout.grid_y0 + layout.grid_y1)
    buckets: List[List[float]] = [[], [], [], []]
    for x, y in payload_coords:
        if y <= y_mid:
            bucket = 0 if x <= x_mid else 1
        else:
            bucket = 2 if x <= x_mid else 3
        buckets[bucket].append(float(avg_gray_u8[y, x]))
    if any(not bucket for bucket in buckets):
        return None
    centers = np.array([float(np.mean(bucket)) for bucket in buckets], dtype=np.float32)
    for idx in range(1, 4):
        if centers[idx] <= centers[idx - 1]:
            centers[idx] = centers[idx - 1] + 1.0
    return centers


def _base_sample_phase_candidates(phi_x: float, phi_y: float) -> List[Tuple[float, float]]:
    candidates = [(0.0, 0.0)]
    if abs(phi_x) > 1e-6 or abs(phi_y) > 1e-6:
        candidates.append((float(phi_x), float(phi_y)))
    return candidates


def _header_threshold_candidates(avg_gray_u8: np.ndarray, layout: Gray4Layout) -> List[int]:
    centers = _fit_gray4_centers(avg_gray_u8, layout)
    values = np.array([int(avg_gray_u8[y, x]) for x, y in layout.data_coords], dtype=np.uint8)
    thresholds = {128, _binary_threshold_from_centers(centers)}
    if values.size >= 16:
        otsu, _ = cv2.threshold(values.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        thresholds.add(int(otsu))
        thresholds.add(int(max(1, min(254, round(0.5 * (float(centers[1]) + float(centers[2])))))))
        thresholds.add(int(max(1, min(254, round(0.5 * (float(centers[0]) + float(centers[2])))))))
        thresholds.add(int(max(1, min(254, round(0.5 * (float(centers[1]) + float(centers[3])))))))
    return sorted(int(max(1, min(254, value))) for value in thresholds)


def _sample_gray4_modules(
    warped: np.ndarray, layout: Gray4Layout, phi_x: float = 0.0, phi_y: float = 0.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, List[float]]:
    """
    Sample gray4 modules from warped image with 3x3 averaging.

    This function replicates the locator's sampling strategy but without
    binarization, preserving grayscale values for 4-level quantization.

    Returns:
        sample_stack_u8: uint8 raw 3x3 sample stack for control/header voting
        avg_gray_u8: uint8 averaged module grayscale values
        header_modules: uint8 array for binary header slicing
        fixed_modules: uint8 array quantized with fixed thresholds
        adaptive_modules: uint8 array quantized with fitted centers
        confidences: list of confidence scores per module
    """
    # Convert to grayscale if needed
    if len(warped.shape) == 3:
        gray = warped.mean(axis=2).astype(np.float32) / 255.0
    else:
        gray = warped.astype(np.float32) / 255.0

    # Calculate cell dimensions
    cell_w = float(warped.shape[1]) / float(layout.frame_w)
    cell_h = float(warped.shape[0]) / float(layout.frame_h)
    h_max = gray.shape[0] - 1
    w_max = gray.shape[1] - 1

    # Pre-compute center coords for every module cell
    cy_base = (np.arange(layout.frame_h, dtype=np.float32) + 0.5 + float(phi_y)) * cell_h
    cx_base = (np.arange(layout.frame_w, dtype=np.float32) + 0.5 + float(phi_x)) * cell_w

    # 3x3 sampling offsets (same as locator)
    offsets = [
        (-0.25, -0.25),
        (-0.25, 0.0),
        (-0.25, 0.25),
        (0.0, -0.25),
        (0.0, 0.0),
        (0.0, 0.25),
        (0.25, -0.25),
        (0.25, 0.0),
        (0.25, 0.25),
    ]

    # Accumulate grayscale values (not binarized)
    sample_stack = []
    vote_sum = np.zeros((layout.frame_h, layout.frame_w), dtype=np.float32)
    for oy, ox in offsets:
        py = np.clip(np.round(cy_base + oy * cell_h).astype(np.int32), 0, h_max)
        px = np.clip(np.round(cx_base + ox * cell_w).astype(np.int32), 0, w_max)
        sample = gray[py[:, None], px[None, :]]
        vote_sum += sample
        sample_stack.append((sample * 255.0).astype(np.uint8))

    # Average grayscale value per module (0.0-1.0)
    avg_gray = vote_sum / 9.0

    # Convert to 0-255 range
    avg_gray_u8 = (avg_gray * 255.0).astype(np.uint8)

    centers = _fit_gray4_centers(avg_gray_u8, layout)

    header_threshold = _binary_threshold_from_centers(centers)

    # Quantize to 4 levels
    header_modules = np.zeros((layout.frame_h, layout.frame_w), dtype=np.uint8)
    fixed_modules = np.zeros((layout.frame_h, layout.frame_w), dtype=np.uint8)
    adaptive_modules = np.zeros((layout.frame_h, layout.frame_w), dtype=np.uint8)
    confidences = []

    for y in range(layout.frame_h):
        for x in range(layout.frame_w):
            avg_value = int(avg_gray_u8[y, x])
            header_modules[y, x] = 1 if avg_value >= header_threshold else 0
            fixed_symbol, _ = _quantize_gray4(avg_value)
            adaptive_symbol, conf = _quantize_gray4_adaptive(avg_value, centers)
            fixed_modules[y, x] = fixed_symbol
            adaptive_modules[y, x] = adaptive_symbol
            confidences.append(conf)

    return np.stack(sample_stack, axis=0), avg_gray_u8, header_modules, fixed_modules, adaptive_modules, confidences


def _sample_gray4_bbox(
    frame: np.ndarray,
    bbox: Tuple[int, int, int, int],
    layout: Gray4Layout,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, List[float]]:
    x, y, w, h = bbox
    crop = frame[y : y + h, x : x + w]
    if len(crop.shape) == 3:
        gray = crop.mean(axis=2).astype(np.float32)
    else:
        gray = crop.astype(np.float32)

    cell_w = float(w) / float(layout.frame_w)
    cell_h = float(h) / float(layout.frame_h)
    sample_stack_u8 = np.zeros((9, layout.frame_h, layout.frame_w), dtype=np.uint8)
    avg_gray_u8 = np.zeros((layout.frame_h, layout.frame_w), dtype=np.uint8)
    header_modules = np.zeros((layout.frame_h, layout.frame_w), dtype=np.uint8)
    fixed_modules = np.zeros((layout.frame_h, layout.frame_w), dtype=np.uint8)
    adaptive_modules = np.zeros((layout.frame_h, layout.frame_w), dtype=np.uint8)
    static_modules = np.zeros((layout.frame_h, layout.frame_w), dtype=np.uint8)
    for yy in range(layout.frame_h):
        y0 = int(round(yy * cell_h))
        y1 = max(y0 + 1, int(round((yy + 1) * cell_h)))
        y0 = max(0, min(gray.shape[0] - 1, y0))
        y1 = max(y0 + 1, min(gray.shape[0], y1))
        for xx in range(layout.frame_w):
            x0 = int(round(xx * cell_w))
            x1 = max(x0 + 1, int(round((xx + 1) * cell_w)))
            x0 = max(0, min(gray.shape[1] - 1, x0))
            x1 = max(x0 + 1, min(gray.shape[1], x1))
            patch = gray[y0:y1, x0:x1]
            avg_value = int(np.mean(patch))
            avg_gray_u8[yy, xx] = np.uint8(avg_value)
            sub_h = max(1, patch.shape[0] // 3)
            sub_w = max(1, patch.shape[1] // 3)
            sample_index = 0
            for sy in range(3):
                py0 = min(patch.shape[0] - 1, sy * sub_h)
                py1 = patch.shape[0] if sy == 2 else min(patch.shape[0], (sy + 1) * sub_h)
                py1 = max(py0 + 1, py1)
                for sx in range(3):
                    px0 = min(patch.shape[1] - 1, sx * sub_w)
                    px1 = patch.shape[1] if sx == 2 else min(patch.shape[1], (sx + 1) * sub_w)
                    px1 = max(px0 + 1, px1)
                    sample_stack_u8[sample_index, yy, xx] = np.uint8(np.mean(patch[py0:py1, px0:px1]))
                    sample_index += 1

    centers = _fit_gray4_centers(avg_gray_u8, layout)
    header_threshold = _binary_threshold_from_centers(centers)
    confidences: List[float] = []
    for yy in range(layout.frame_h):
        for xx in range(layout.frame_w):
            avg_value = int(avg_gray_u8[yy, xx])
            header_modules[yy, xx] = 1 if avg_value >= header_threshold else 0
            fixed_symbol, _ = _quantize_gray4(avg_value)
            adaptive_symbol, conf = _quantize_gray4_adaptive(avg_value, centers)
            fixed_modules[yy, xx] = fixed_symbol
            adaptive_modules[yy, xx] = adaptive_symbol
            static_modules[yy, xx] = 1 if fixed_symbol >= 2 else 0
            confidences.append(conf)

    return sample_stack_u8, avg_gray_u8, header_modules, fixed_modules, adaptive_modules, static_modules, confidences


def _read_format_bits_gray4(modules: np.ndarray, layout: Gray4Layout, *, binary: bool = False) -> bytes:
    """Read binary format info from either binary or quantized module matrices."""
    if binary:
        bits = [int(modules[y, x]) & 1 for x, y in layout.format_coords]
    else:
        bits = [1 if int(modules[y, x]) >= 2 else 0 for x, y in layout.format_coords]
    unit_len = (FORMAT_SIZE + 2) * 8  # 80 bits

    # Determine repetition level based on available coordinates
    available_bits = len(bits)
    if available_bits >= unit_len * 3:
        # Full 3x repetition
        rep = 3
        threshold = 2
    elif available_bits >= unit_len * 2:
        # 2x repetition
        rep = 2
        threshold = 1
    elif available_bits >= unit_len:
        # No repetition
        rep = 1
        threshold = 0
    else:
        raise ValueError(f"format area too small: {available_bits} < {unit_len}")

    # Extract and vote
    raw_bits = bits[: unit_len * rep]
    voted = []
    for i in range(unit_len):
        s = 0
        for r in range(rep):
            idx = r * unit_len + i
            if idx < len(raw_bits):
                s += raw_bits[idx]
        voted.append(1 if s > threshold else 0)

    # Convert bits to bytes
    out = bytearray()
    for i in range(0, len(voted), 8):
        v = 0
        for b in voted[i : i + 8]:
            v = (v << 1) | (b & 1)
        out.append(v)
    return bytes(out)


def _read_layout_info_gray4(
    modules: np.ndarray, layout: Gray4Layout, *, binary: bool = False
) -> Optional[LayoutInfoCompact]:
    """Read binary layout info from gray4 modules with adaptive repetition."""
    if not layout.layout_coords:
        return None

    unit_len = len(LayoutInfoCompact().pack()) * 8
    available_bits = len(layout.layout_coords)

    # Determine repetition level based on available coordinates
    if available_bits >= unit_len * 2:
        # Full 2x repetition
        rep = 2
        threshold = 1
    elif available_bits >= unit_len:
        # No repetition
        rep = 1
        threshold = 0
    else:
        return None  # Not enough coordinates

    if binary:
        bits = [int(modules[y, x]) & 1 for x, y in layout.layout_coords[: unit_len * rep]]
    else:
        bits = [1 if int(modules[y, x]) >= 2 else 0 for x, y in layout.layout_coords[: unit_len * rep]]
    if len(bits) < unit_len * rep:
        return None

    # Vote
    voted = []
    for i in range(unit_len):
        s = 0
        for r in range(rep):
            idx = r * unit_len + i
            if idx < len(bits):
                s += bits[idx]
        voted.append(1 if s > threshold else 0)

    # Convert to bytes
    raw = bytearray()
    for i in range(0, len(voted), 8):
        v = 0
        for b in voted[i : i + 8]:
            v = (v << 1) | int(b)
        raw.append(v)

    try:
        return LayoutInfoCompact.unpack(bytes(raw))
    except LayoutInfoError:
        return None


def _decode_modules_gray4(
    sample_stack_u8: np.ndarray,
    avg_gray_u8: np.ndarray,
    header_modules: np.ndarray,
    fixed_modules: np.ndarray,
    adaptive_modules: np.ndarray,
    static_modules: np.ndarray,
    layout: Gray4Layout,
    confidences: List[float],
    calibration_by_mask: Optional[Dict[int, np.ndarray]] = None,
) -> Tuple[FrameHeaderBasic, bytes, int, float, int, int]:
    """
    Decode gray4 modules to header and payload.

    Returns:
        header, payload, mask_id, avg_confidence
    """
    mask_candidates: List[int]
    ecc_candidates: List[str]

    # Try to read format info
    try:
        fmt = FormatInfoBasic.unpack(_read_format_bits_gray4(static_modules, layout, binary=True))
        mask_candidates = [int(fmt.mask_id)]
        ecc_candidates = [ID_TO_ECC.get(int(fmt.ecc_id), ECC_Q)]
    except Exception:
        # Fallback to exhaustive search when the binary format area is corrupted.
        mask_candidates = list(range(8))
        ecc_candidates = ["L", "M", "Q", "H"]
    
    last_exc = None
    def _decode_legacy_stream(
        mask_id: int, rep: int, symbol_modules: np.ndarray
    ) -> Tuple[FrameHeaderBasic, bytes]:
        symbols = []
        for x, y in layout.data_coords:
            sym = int(symbol_modules[y, x]) & 0x03
            if _mask_bit(mask_id, x, y):
                sym ^= 0x03
            symbols.append(sym)
        dec_symbols = decode_repetition_symbols(symbols, rep)
        raw = decode_gray4_symbols(dec_symbols, HEADER_SIZE + 2)
        header = FrameHeaderBasic.unpack(raw[:HEADER_SIZE])
        payload_len = int(header.payload_len)
        raw = decode_gray4_symbols(dec_symbols, HEADER_SIZE + payload_len)
        header = FrameHeaderBasic.unpack(raw[:HEADER_SIZE])
        payload = raw[HEADER_SIZE : HEADER_SIZE + payload_len]
        validate_payload_crc(header.payload_crc32, payload)
        return header, payload

    def _payload_symbols_for_modules(
        symbol_modules: np.ndarray, payload_coords: List[Tuple[int, int]], mask_id: int, limit: int
    ) -> List[int]:
        payload_symbols: List[int] = []
        for x, y in payload_coords[:limit]:
            sym = int(symbol_modules[y, x]) & 0x03
            if _mask_bit(mask_id, x, y):
                sym ^= 0x03
            payload_symbols.append(sym)
        return payload_symbols

    def _payload_confidences_for_coords(payload_coords: List[Tuple[int, int]]) -> List[float]:
        values: List[float] = []
        for x, y in payload_coords:
            idx = y * layout.frame_w + x
            values.append(float(confidences[idx]) if idx < len(confidences) else 1.0)
        return values

    def _decode_payload_variant_search(
        *,
        payload_variants: List[List[int]],
        payload_confidences: List[float],
        payload_len: int,
        rep: int,
    ) -> Tuple[bytes, int, int]:
        low_conf_threshold = 0.45
        if not payload_variants:
            raise RuntimeError("gray4 payload variant search has no variants")
        base_payload_symbols = payload_variants[-1]
        candidate_indices = [
            idx
            for idx, conf in enumerate(payload_confidences)
            if conf < low_conf_threshold
            and len({variant[idx] for variant in payload_variants if idx < len(variant)}) > 1
        ]
        candidate_indices.sort(key=lambda idx: payload_confidences[idx])
        candidate_indices = candidate_indices[:4]
        low_conf_count = len(candidate_indices)
        if not candidate_indices:
            raise RuntimeError("gray4 payload variant search has no candidates")

        variant_sets: List[Tuple[int, ...]] = []
        for idx in candidate_indices:
            variant_sets.append((idx,))
        if len(candidate_indices) >= 2:
            variant_sets.append((candidate_indices[0], candidate_indices[1]))
        if len(candidate_indices) >= 3:
            variant_sets.append((candidate_indices[0], candidate_indices[2]))

        attempts = 0
        last_exc: Optional[Exception] = None
        alt_values: List[List[int]] = []
        for idx in candidate_indices:
            values = sorted({variant[idx] for variant in payload_variants if idx < len(variant)})
            alt_values.append(values)

        for flip_indices in variant_sets:
            attempts += 1
            variant = list(base_payload_symbols)
            for idx in flip_indices:
                local = candidate_indices.index(idx)
                for candidate_sym in alt_values[local]:
                    if candidate_sym == variant[idx]:
                        continue
                    trial = list(variant)
                    trial[idx] = candidate_sym
                    try:
                        dec_symbols = decode_repetition_symbols(trial, rep)
                        payload = decode_gray4_symbols(dec_symbols, payload_len)
                        return payload, attempts, low_conf_count
                    except Exception as exc:  # noqa: PERF203
                        last_exc = exc
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("gray4 payload variant search failed")

    for mask_id in mask_candidates:
        binary_header_cache = {}
        data_confidences = _payload_confidences_for_coords(layout.data_coords)

        avg_conf = float(np.mean(data_confidences)) if data_confidences else 0.0

        for ecc in ecc_candidates:
            try:
                rep = ECC_TO_REP[ecc]
                header_rep_candidates = []
                for candidate in (gray4_header_repetition(rep), rep):
                    if candidate not in header_rep_candidates:
                        header_rep_candidates.append(candidate)

                for header_rep in header_rep_candidates:
                    header_cell_count = HEADER_SIZE * 8 * header_rep
                    if header_cell_count > len(layout.data_coords):
                        continue

                    header_key = (mask_id, rep, header_rep)
                    if header_key not in binary_header_cache:
                        binary_header_cache[header_key] = decode_binary_control_header(
                            avg_gray_u8=avg_gray_u8,
                            header_maps=[header_modules],
                            sample_stack_u8=sample_stack_u8,
                            thresholds=_header_threshold_candidates(avg_gray_u8, layout),
                            data_coords=layout.data_coords,
                            header_size_bytes=HEADER_SIZE,
                            repetition=header_rep,
                            mask_id=mask_id,
                            mask_bit_fn=_mask_bit,
                            unpack_header=FrameHeaderBasic.unpack,
                        )
                    header = binary_header_cache[header_key]
                    payload_len = int(header.payload_len)

                    payload_coords = layout.data_coords[header_cell_count:]
                    symbols_needed = payload_len * 4 * rep
                    symbol_module_candidates = [fixed_modules]
                    if not np.array_equal(adaptive_modules, fixed_modules):
                        symbol_module_candidates.append(adaptive_modules)

                    if symbols_needed > len(payload_coords):
                        for symbol_modules in symbol_module_candidates:
                            try:
                                header, payload = _decode_legacy_stream(mask_id, rep, symbol_modules)
                                return header, payload, mask_id, avg_conf, 0, 0
                            except Exception as legacy_exc:
                                last_exc = legacy_exc
                        continue

                    payload_variants = [
                        (
                            symbol_modules,
                            _payload_symbols_for_modules(
                                symbol_modules, payload_coords, mask_id, symbols_needed
                            ),
                        )
                        for symbol_modules in symbol_module_candidates
                    ]

                    calibration_payload_confidences: Optional[List[float]] = None
                    payload_calibration_centers = None
                    if calibration_by_mask is not None:
                        candidate_centers = calibration_by_mask.get(int(mask_id))
                        if candidate_centers is not None and getattr(candidate_centers, "shape", None) == (4,):
                            payload_calibration_centers = candidate_centers
                    if payload_calibration_centers is not None:
                        calibrated_symbols: List[int] = []
                        calibration_payload_confidences = []
                        for x, y in payload_coords[:symbols_needed]:
                            sym, conf = _quantize_gray4_adaptive(
                                int(avg_gray_u8[y, x]), payload_calibration_centers
                            )
                            if _mask_bit(mask_id, x, y):
                                sym ^= 0x03
                            calibrated_symbols.append(sym)
                            calibration_payload_confidences.append(conf)
                        payload_variants.append((adaptive_modules, calibrated_symbols))

                    payload_confidences_for_retry = (
                        calibration_payload_confidences
                        if calibration_payload_confidences is not None
                        else _payload_confidences_for_coords(payload_coords[:symbols_needed])
                    )

                    for symbol_modules, payload_symbols in payload_variants:
                        try:
                            dec_symbols = decode_repetition_symbols(payload_symbols, rep)
                            payload = decode_gray4_symbols(dec_symbols, payload_len)
                            validate_payload_crc(header.payload_crc32, payload)
                            return header, payload, mask_id, avg_conf, 0, 0
                        except Exception as payload_exc:
                            last_exc = payload_exc

                    if len(payload_variants) >= 2:
                        try:
                            payload, variant_attempts, low_conf_count = _decode_payload_variant_search(
                                payload_variants=[variant[1] for variant in payload_variants],
                                payload_confidences=payload_confidences_for_retry,
                                payload_len=payload_len,
                                rep=rep,
                            )
                            validate_payload_crc(header.payload_crc32, payload)
                            return (
                                header,
                                payload,
                                mask_id,
                                avg_conf,
                                variant_attempts,
                                low_conf_count,
                            )
                        except Exception as variant_exc:
                            last_exc = variant_exc
            except Exception as exc:  # noqa: PERF203
                for symbol_modules in (fixed_modules, adaptive_modules):
                    try:
                        header, payload = _decode_legacy_stream(mask_id, rep, symbol_modules)
                        return header, payload, mask_id, avg_conf, 0, 0
                    except Exception as legacy_exc:  # noqa: PERF203
                        last_exc = legacy_exc if str(legacy_exc) else exc
    
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("gray4 decode failed")


def _bbox_from_quad(
    quad: np.ndarray, frame_shape: Tuple[int, int, int]
) -> tuple[int, int, int, int]:
    """Compute bounding box from quad."""
    h, w = frame_shape[:2]
    x1 = max(0, int(np.floor(float(np.min(quad[:, 0])))))
    y1 = max(0, int(np.floor(float(np.min(quad[:, 1])))))
    x2 = min(w, int(np.ceil(float(np.max(quad[:, 0])))))
    y2 = min(h, int(np.ceil(float(np.max(quad[:, 1])))))
    return x1, y1, max(1, x2 - x1), max(1, y2 - y1)


def _try_axis_aligned_decode(
    frame: np.ndarray,
    layout: Gray4Layout,
    calibration_by_mask: Optional[Dict[int, np.ndarray]] = None,
) -> Optional[Tuple[FrameHeaderBasic, bytes, DecodeMetaGray4]]:
    started = time.perf_counter()
    bbox = _bbox_from_non_black(frame)
    if bbox is None:
        return None

    bx, by, bw, bh = bbox
    if bw < 128 or bh < 128:
        return None

    aspect = float(layout.frame_w) / float(layout.frame_h)
    bbox_aspect = float(bw) / float(max(1, bh))
    if abs(bbox_aspect - aspect) / aspect > 0.08:
        return None

    sample_stack_u8, avg_gray_u8, header_modules, fixed_modules, adaptive_modules, static_modules, confidences = _sample_gray4_bbox(
        frame, bbox, layout
    )
    parsed = _read_layout_info_gray4(static_modules, layout, binary=True)
    if parsed is not None:
        layout = build_layout_gray4(
            grid_w=parsed.grid_w,
            grid_h=parsed.grid_h,
            guard_band=parsed.guard,
            corner_size=parsed.finder,
        )
        sample_stack_u8, avg_gray_u8, header_modules, fixed_modules, adaptive_modules, static_modules, confidences = _sample_gray4_bbox(
            frame, bbox, layout
        )

    try:
        header, payload, mask_id, avg_conf, payload_variant_attempts, payload_low_conf_symbols = _decode_modules_gray4(
            sample_stack_u8,
            avg_gray_u8,
            header_modules,
            fixed_modules,
            adaptive_modules,
            static_modules,
            layout,
            confidences,
            calibration_by_mask=calibration_by_mask,
        )
        calibration_centers = None
        if int(header.frame_type) == int(FRAME_SYNC):
            header_rep = gray4_header_repetition(ECC_TO_REP[ECC_Q])
            frame_calibration = _sync_calibration_centers(
                avg_gray_u8, layout, HEADER_SIZE * 8 * header_rep
            )
            if frame_calibration is not None:
                calibration_centers = tuple(float(v) for v in frame_calibration.tolist())
        return (
            header,
            payload,
            DecodeMetaGray4(
                protocol_version_used=41,
                locator_engine="axis",
                confidence=1.0,
                fail_reason="",
                elapsed_ms=0.0,
                legacy_used=False,
                homography_rmse=0.0,
                rs_corrected_symbols=0,
                crc_ok=True,
                mask_id=int(mask_id),
                grid_size="{0}x{1}".format(layout.grid_w, layout.grid_h),
                det_bbox=(int(bx), int(by), int(bw), int(bh)),
                decode_attempts=1,
                det_confidence=1.0,
                new_fail_reason="",
                new_elapsed_ms=0.0,
                legacy_elapsed_ms=0.0,
                locator_debug_artifacts={"axis_bbox": [int(bx), int(by), int(bw), int(bh)]},
                locator_warped_preview=None,
                avg_symbol_confidence=avg_conf,
                total_decode_ms=(time.perf_counter() - started) * 1000.0,
                phase_candidates_tried=1,
                phase_sweep_used=False,
                payload_low_conf_symbols=payload_low_conf_symbols,
                payload_variant_attempts=payload_variant_attempts,
                calibration_centers=calibration_centers,
            ),
        )
    except Exception:
        return None


def _try_centered_decode(
    frame: np.ndarray,
    layout: Gray4Layout,
    calibration_by_mask: Optional[Dict[int, np.ndarray]] = None,
) -> Optional[Tuple[FrameHeaderBasic, bytes, DecodeMetaGray4]]:
    started = time.perf_counter()
    frame_h, frame_w = frame.shape[:2]
    scale = max(1, min(frame_w // layout.frame_w, frame_h // layout.frame_h))
    sym_w = layout.frame_w * scale
    sym_h = layout.frame_h * scale
    if sym_w <= 0 or sym_h <= 0:
        return None
    bbox = ((frame_w - sym_w) // 2, (frame_h - sym_h) // 2, sym_w, sym_h)
    bx, by, bw, bh = bbox
    if bx < 0 or by < 0 or bw < 128 or bh < 128:
        return None

    try:
        sample_stack_u8, avg_gray_u8, header_modules, fixed_modules, adaptive_modules, static_modules, confidences = _sample_gray4_bbox(
            frame,
            bbox,
            layout,
        )
        parsed = _read_layout_info_gray4(static_modules, layout, binary=True)
        if parsed is not None:
            layout = build_layout_gray4(
                grid_w=parsed.grid_w,
                grid_h=parsed.grid_h,
                guard_band=parsed.guard,
                corner_size=parsed.finder,
            )
            sample_stack_u8, avg_gray_u8, header_modules, fixed_modules, adaptive_modules, static_modules, confidences = _sample_gray4_bbox(
                frame,
                bbox,
                layout,
            )

        header, payload, mask_id, avg_conf, payload_variant_attempts, payload_low_conf_symbols = _decode_modules_gray4(
            sample_stack_u8,
            avg_gray_u8,
            header_modules,
            fixed_modules,
            adaptive_modules,
            static_modules,
            layout,
            confidences,
            calibration_by_mask=calibration_by_mask,
        )
        calibration_centers = None
        if int(header.frame_type) == int(FRAME_SYNC):
            header_rep = gray4_header_repetition(ECC_TO_REP[ECC_Q])
            frame_calibration = _sync_calibration_centers(
                avg_gray_u8, layout, HEADER_SIZE * 8 * header_rep
            )
            if frame_calibration is not None:
                calibration_centers = tuple(float(v) for v in frame_calibration.tolist())
        return (
            header,
            payload,
            DecodeMetaGray4(
                protocol_version_used=41,
                locator_engine="center",
                confidence=1.0,
                fail_reason="",
                elapsed_ms=0.0,
                legacy_used=False,
                homography_rmse=0.0,
                rs_corrected_symbols=0,
                crc_ok=True,
                mask_id=int(mask_id),
                grid_size="{0}x{1}".format(layout.grid_w, layout.grid_h),
                det_bbox=(int(bx), int(by), int(bw), int(bh)),
                decode_attempts=1,
                det_confidence=1.0,
                new_fail_reason="",
                new_elapsed_ms=0.0,
                legacy_elapsed_ms=0.0,
                locator_debug_artifacts={"center_bbox": [int(bx), int(by), int(bw), int(bh)]},
                locator_warped_preview=None,
                avg_symbol_confidence=avg_conf,
                total_decode_ms=(time.perf_counter() - started) * 1000.0,
                phase_candidates_tried=1,
                phase_sweep_used=False,
                payload_low_conf_symbols=payload_low_conf_symbols,
                payload_variant_attempts=payload_variant_attempts,
                calibration_centers=calibration_centers,
            ),
        )
    except Exception:
        return None


def decode_frame_gray4(
    frame: np.ndarray,
    detect_mode: str = "full",
    forced_roi: Optional[Tuple[int, int, int, int]] = None,
    grid_w: int = DEFAULT_GRID_W_COMPACT,
    grid_h: int = DEFAULT_GRID_H_COMPACT,
    guard_band: int = DEFAULT_GUARD_COMPACT,
    corner_size: int = DEFAULT_FINDER_COMPACT,
    roi_only: bool = False,
    manual_strict: bool = False,
    locator_engine: str = "auto",
    locator_confidence_threshold: float = 0.55,
    calibration_by_mask: Optional[Dict[int, np.ndarray]] = None,
) -> Tuple[FrameHeaderBasic, bytes, DecodeMetaGray4]:
    """
    Decode a gray4 frame with 4-level grayscale demodulation.

    Gray4 reuses the compact locator/layout contract and only changes payload modulation.
    """
    started = time.perf_counter()
    if detect_mode not in ("full", "track", "roi"):
        raise ValueError("invalid detect_mode")
    if locator_engine not in ("new", "legacy", "auto"):
        raise ValueError("invalid locator_engine")
    
    # Determine search ROI
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

    if detect_mode == "full" and search_roi is None:
        axis_result = _try_axis_aligned_decode(
            frame,
            build_layout_gray4(
                grid_w=grid_w, grid_h=grid_h, guard_band=guard_band, corner_size=corner_size
            ),
            calibration_by_mask=calibration_by_mask,
        )
        if axis_result is not None:
            return axis_result

    def _decode_from_loc(
        loc: LocateResult,
        used_engine: str,
        new_err: Optional[LocateError],
        legacy_err: Optional[LocateError],
    ) -> Tuple[FrameHeaderBasic, bytes, DecodeMetaGray4]:
        layout = build_layout_gray4(
            grid_w=grid_w, grid_h=grid_h, guard_band=guard_band, corner_size=corner_size
        )
        phi_x = float(loc.debug_artifacts.get("timing_phi_x", 0.0))
        phi_y = float(loc.debug_artifacts.get("timing_phi_y", 0.0))

        parsed = _read_layout_info_gray4(loc.modules, layout, binary=True)
        if parsed is not None:
            layout = build_layout_gray4(
                grid_w=parsed.grid_w,
                grid_h=parsed.grid_h,
                guard_band=parsed.guard,
                corner_size=parsed.finder,
            )

        last_exc = None
        attempts = 0

        sample_variants = _base_sample_phase_candidates(phi_x, phi_y)

        for sample_phi_x, sample_phi_y in sample_variants:
            sample_stack_u8, avg_gray_u8, header_modules, fixed_modules, adaptive_modules, confidences = _sample_gray4_modules(
                loc.warped, layout, phi_x=sample_phi_x, phi_y=sample_phi_y
            )
            attempts += 1
            try:
                header, payload, mask_id, avg_conf, payload_variant_attempts, payload_low_conf_symbols = _decode_modules_gray4(
                    sample_stack_u8,
                    avg_gray_u8,
                    header_modules,
                    fixed_modules,
                    adaptive_modules,
                    loc.modules,
                    layout,
                    confidences,
                    calibration_by_mask=calibration_by_mask,
                )
                bbox = _bbox_from_quad(loc.quad_src, frame.shape)
                calibration_centers = None
                if int(header.frame_type) == int(FRAME_SYNC):
                    header_rep = gray4_header_repetition(ECC_TO_REP[ECC_Q])
                    frame_calibration = _sync_calibration_centers(
                        avg_gray_u8, layout, HEADER_SIZE * 8 * header_rep
                    )
                    if frame_calibration is not None:
                        calibration_centers = tuple(float(v) for v in frame_calibration.tolist())
                return (
                    header,
                    payload,
                    DecodeMetaGray4(
                        protocol_version_used=41,
                        locator_engine=used_engine,
                        confidence=float(loc.quality.confidence),
                        fail_reason="" if loc.fail_reason is None else loc.fail_reason.value,
                        elapsed_ms=float(loc.elapsed_ms),
                        legacy_used=bool(loc.legacy_used),
                        homography_rmse=float(loc.quality.warp_rmse),
                        rs_corrected_symbols=0,
                        crc_ok=True,
                        mask_id=int(mask_id),
                        grid_size="{0}x{1}".format(layout.grid_w, layout.grid_h),
                        det_bbox=bbox,
                        decode_attempts=attempts,
                        det_confidence=float(loc.quality.confidence),
                        new_fail_reason="" if new_err is None else new_err.fail_reason.value,
                        new_elapsed_ms=0.0 if new_err is None else float(new_err.elapsed_ms),
                        legacy_elapsed_ms=float(loc.elapsed_ms) if loc.legacy_used else 0.0,
                        locator_debug_artifacts=dict(loc.debug_artifacts),
                        locator_warped_preview=loc.warped.copy(),
                        avg_symbol_confidence=avg_conf,
                        total_decode_ms=(time.perf_counter() - started) * 1000.0,
                        phase_candidates_tried=attempts,
                        phase_sweep_used=False,
                        payload_low_conf_symbols=payload_low_conf_symbols,
                        payload_variant_attempts=payload_variant_attempts,
                        calibration_centers=calibration_centers,
                    ),
                )
            except Exception as exc:
                last_exc = exc
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("gray4 decode failed")

    loc, used_engine, new_err, legacy_err = _run_locator_compact(
        frame=frame,
        locator_engine=locator_engine,
        search_roi=search_roi,
        cfg=cfg,
    )
    try:
        return _decode_from_loc(loc, used_engine, new_err, legacy_err)
    except Exception as first_exc:
        if locator_engine == "auto" and used_engine != "legacy":
            legacy_loc, legacy_used_engine, _, _ = _run_locator_compact(
                frame=frame,
                locator_engine="legacy",
                search_roi=search_roi,
                cfg=cfg,
            )
            try:
                return _decode_from_loc(legacy_loc, legacy_used_engine, new_err, None)
            except Exception:
                pass
        raise first_exc
