"""Decode frames into header/payload and validate CRC."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from screen_airdrop.common.protocol import (
    HEADER_SIZE_V1,
    HEADER_SIZE_V2,
    PROTOCOL_VERSION_V1,
    PROTOCOL_VERSION_V2,
    FrameHeader,
    v2_payload_inset_px,
    validate_payload_crc,
)
from screen_airdrop.receiver.locator import detect_locator_bbox


@dataclass
class DecodeMeta:
    protocol_version_used: int
    locator_confidence: float
    locator_failed: bool


def bits_to_bytes(bits: np.ndarray) -> bytes:
    if bits.size == 0:
        return b""
    valid = (bits.size // 8) * 8
    if valid == 0:
        return b""
    packed = np.packbits(bits[:valid])
    return packed.tobytes()


def frame_to_bits(frame: np.ndarray, block_size: int, threshold: int) -> np.ndarray:
    h, w = frame.shape[:2]
    rows = h // block_size
    cols = w // block_size
    if rows <= 0 or cols <= 0:
        return np.zeros((0,), dtype=np.uint8)
    crop = frame[: rows * block_size, : cols * block_size]
    gray = crop.mean(axis=2)
    grid = gray.reshape(rows, block_size, cols, block_size).mean(axis=(1, 3))
    bits = (grid > threshold).astype(np.uint8).reshape(-1)
    return bits


def _decode_bits_as_header_payload(bits: np.ndarray, header_bits: int) -> Tuple[FrameHeader, bytes]:
    if bits.size < header_bits:
        raise ValueError("frame too small to contain header")

    header_bytes = bits_to_bytes(bits[:header_bits])
    header = FrameHeader.unpack(header_bytes)

    payload_bits_len = header.payload_len * 8
    payload_bits = bits[header_bits : header_bits + payload_bits_len]
    payload = bits_to_bytes(payload_bits)
    if len(payload) != header.payload_len:
        raise ValueError("payload length mismatch")

    validate_payload_crc(header, payload)
    return header, payload


def _decode_v1(frame: np.ndarray, block_size: int, threshold: int) -> Tuple[FrameHeader, bytes, DecodeMeta]:
    bits = frame_to_bits(frame, block_size=block_size, threshold=threshold)
    header, payload = _decode_bits_as_header_payload(bits, HEADER_SIZE_V1 * 8)
    if header.version != PROTOCOL_VERSION_V1:
        raise ValueError("not a v1 frame")
    return header, payload, DecodeMeta(protocol_version_used=1, locator_confidence=0.0, locator_failed=False)


def _decode_v2(
    frame: np.ndarray,
    block_size: int,
    threshold: int,
    forced_roi: Optional[Tuple[int, int, int, int]] = None,
) -> Tuple[FrameHeader, bytes, DecodeMeta]:
    def _decode_payload_view(payload_view: np.ndarray) -> Tuple[FrameHeader, bytes]:
        bits = frame_to_bits(payload_view, block_size=block_size, threshold=threshold)
        header, payload = _decode_bits_as_header_payload(bits, HEADER_SIZE_V2 * 8)
        if header.version != PROTOCOL_VERSION_V2:
            raise ValueError("not a v2 frame")
        return header, payload

    def _decode_payload_view_with_offsets(payload_view: np.ndarray) -> Tuple[FrameHeader, bytes]:
        # Capture/compositor may introduce 1-2 px misalignment; try a small offset search.
        max_oy = min(block_size, max(1, payload_view.shape[0] - 1))
        max_ox = min(block_size, max(1, payload_view.shape[1] - 1))
        last_exc = None
        for oy in range(max_oy):
            for ox in range(max_ox):
                sub = payload_view[oy:, ox:]
                if sub.shape[0] < block_size * 4 or sub.shape[1] < block_size * 4:
                    continue
                try:
                    return _decode_payload_view(sub)
                except Exception as exc:  # noqa: PERF203
                    last_exc = exc
                    continue
        if last_exc is not None:
            raise last_exc
        raise ValueError("payload view too small")

    def _decode_from_locator_roi(roi_frame: np.ndarray, border_px: int) -> Tuple[FrameHeader, bytes]:
        last_exc = None
        for delta in range(-block_size, block_size + 1):
            b = border_px + delta
            if b <= 0:
                continue
            if roi_frame.shape[1] <= 2 * b or roi_frame.shape[0] <= 2 * b:
                continue
            payload_view = roi_frame[b : roi_frame.shape[0] - b, b : roi_frame.shape[1] - b]
            try:
                return _decode_payload_view_with_offsets(payload_view)
            except Exception as exc:  # noqa: PERF203
                last_exc = exc
                continue
        if last_exc is not None:
            raise last_exc
        raise ValueError("locator roi too small")

    def _decode_from_locator_roi_compatible(roi_frame: np.ndarray) -> Tuple[FrameHeader, bytes]:
        # Compatible with old single-ring v2 layout and new multi-layer v2 layout.
        primary = v2_payload_inset_px(block_size)
        fallbacks = [primary, 2 * block_size]
        seen = set()
        last_exc = None
        for inset in fallbacks:
            if inset in seen:
                continue
            seen.add(inset)
            try:
                return _decode_from_locator_roi(roi_frame, border_px=inset)
            except Exception as exc:  # noqa: PERF203
                last_exc = exc
                continue
        if last_exc is not None:
            raise last_exc
        raise ValueError("locator roi decode failed")

    def _decode_from_roi_with_inset_search(roi_frame: np.ndarray) -> Tuple[FrameHeader, bytes]:
        # Some detectors may return a larger parent box (e.g. full sender window).
        # Try progressively inset crops to converge to the true locator ring.
        max_extra = min(roi_frame.shape[0] // 4, roi_frame.shape[1] // 4, 12 * block_size)
        extras = [0]
        step = max(1, block_size)
        cur = step
        while cur <= max_extra:
            extras.append(cur)
            cur += step
        last_exc = None
        for extra in extras:
            if extra <= 0:
                sub = roi_frame
            else:
                if roi_frame.shape[0] <= 2 * extra or roi_frame.shape[1] <= 2 * extra:
                    continue
                sub = roi_frame[extra : roi_frame.shape[0] - extra, extra : roi_frame.shape[1] - extra]
            try:
                return _decode_from_locator_roi_compatible(sub)
            except Exception as exc:  # noqa: PERF203
                last_exc = exc
                continue
        if last_exc is not None:
            raise last_exc
        raise ValueError("roi inset search failed")

    if forced_roi is not None:
        x, y, w, h = forced_roi
        x = max(0, int(x))
        y = max(0, int(y))
        w = max(1, int(w))
        h = max(1, int(h))
        roi_frame = frame[y : y + h, x : x + w]
        detected = detect_locator_bbox(roi_frame, threshold=threshold)
        candidate_rois = []
        if detected is not None:
            dx, dy, dw, dh = detected.bbox
            candidate_rois.append(roi_frame[dy : dy + dh, dx : dx + dw])
            conf = float(detected.confidence)
            locator_failed = False
        else:
            conf = 0.0
            locator_failed = True
        # Always keep user's original ROI as fallback: internal locator may lock onto inner ring.
        candidate_rois.append(roi_frame)
    else:
        candidates = []
        detected = detect_locator_bbox(frame, threshold=threshold, use_projection=True)
        if detected is not None:
            candidates.append(detected)
        detected_cc = detect_locator_bbox(frame, threshold=threshold, use_projection=False)
        if detected_cc is not None:
            if not candidates or detected_cc.bbox != candidates[0].bbox:
                candidates.append(detected_cc)
        if not candidates:
            raise ValueError("locator not found")
        decode_errors = []
        selected = None
        for cand in candidates:
            x, y, w, h = cand.bbox
            roi_frame = frame[y : y + h, x : x + w]
            border_px = v2_payload_inset_px(block_size)
            if roi_frame.shape[1] <= 2 * border_px or roi_frame.shape[0] <= 2 * border_px:
                continue
            payload_view = roi_frame[
                border_px : roi_frame.shape[0] - border_px,
                border_px : roi_frame.shape[1] - border_px,
            ]
            try:
                header, payload = _decode_payload_view(payload_view)
                conf = float(cand.confidence)
                locator_failed = False
                return header, payload, DecodeMeta(protocol_version_used=2, locator_confidence=conf, locator_failed=locator_failed)
            except Exception as exc:
                decode_errors.append(exc)
                selected = cand
        if decode_errors:
            raise decode_errors[-1]
        if selected is None:
            raise ValueError("locator roi too small")
        raise ValueError("locator decode failed")

    border_px = v2_payload_inset_px(block_size)
    if forced_roi is not None and locator_failed:
        decode_errors = []
        for cand in candidate_rois:
            if cand.shape[1] > 2 * border_px and cand.shape[0] > 2 * border_px:
                try:
                    header, payload = _decode_from_roi_with_inset_search(cand)
                    return header, payload, DecodeMeta(protocol_version_used=2, locator_confidence=conf, locator_failed=locator_failed)
                except Exception as exc:
                    decode_errors.append(exc)
            try:
                header, payload = _decode_payload_view_with_offsets(cand)
                return header, payload, DecodeMeta(protocol_version_used=2, locator_confidence=conf, locator_failed=locator_failed)
            except Exception as exc:
                decode_errors.append(exc)
        raise ValueError("manual roi decode failed: {0}".format(decode_errors[-1]))

    if forced_roi is not None and not locator_failed:
        decode_errors = []
        for cand in candidate_rois:
            try:
                header, payload = _decode_from_roi_with_inset_search(cand)
                return header, payload, DecodeMeta(protocol_version_used=2, locator_confidence=conf, locator_failed=locator_failed)
            except Exception as exc:
                decode_errors.append(exc)
                try:
                    header, payload = _decode_payload_view_with_offsets(cand)
                    return header, payload, DecodeMeta(protocol_version_used=2, locator_confidence=conf, locator_failed=locator_failed)
                except Exception as exc2:  # noqa: PERF203
                    decode_errors.append(exc2)
        raise ValueError("manual roi decode failed: {0}".format(decode_errors[-1]))

    header, payload = _decode_from_roi_with_inset_search(roi_frame)

    return header, payload, DecodeMeta(protocol_version_used=2, locator_confidence=conf, locator_failed=locator_failed)


def decode_frame(
    frame: np.ndarray,
    block_size: int,
    threshold: int,
    protocol: str = "v2",
    forced_roi: Optional[Tuple[int, int, int, int]] = None,
) -> Tuple[FrameHeader, bytes, DecodeMeta]:
    if protocol == "v1":
        return _decode_v1(frame, block_size=block_size, threshold=threshold)
    if protocol == "v2":
        return _decode_v2(frame, block_size=block_size, threshold=threshold, forced_roi=forced_roi)

    # auto mode: try v2 first, then v1 fallback.
    try:
        return _decode_v2(frame, block_size=block_size, threshold=threshold, forced_roi=forced_roi)
    except Exception:
        return _decode_v1(frame, block_size=block_size, threshold=threshold)
