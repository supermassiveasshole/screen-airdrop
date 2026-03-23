"""Robust control/header decode helpers shared by receiver transports."""

from __future__ import annotations

from itertools import combinations
from typing import Callable, List, Sequence, Tuple, TypeVar

import numpy as np

T = TypeVar("T")


def bits_to_bytes(bits: Sequence[int]) -> bytes:
    out = bytearray()
    for i in range(0, len(bits), 8):
        v = 0
        for b in bits[i : i + 8]:
            v = (v << 1) | (int(b) & 1)
        out.append(v)
    return bytes(out)


def _logical_bits_from_scores(group_scores: Sequence[float]) -> List[int]:
    return [1 if float(score) >= 0.0 else 0 for score in group_scores]


def _logical_scores_for_map(
    *,
    candidate_map: np.ndarray,
    sample_stack_u8: np.ndarray | None,
    threshold: int | None,
    data_coords: Sequence[Tuple[int, int]],
    header_cell_count: int,
    repetition: int,
    mask_id: int,
    mask_bit_fn: Callable[[int, int, int], int],
) -> List[float]:
    cell_scores: List[float] = []
    for x, y in data_coords[:header_cell_count]:
        if sample_stack_u8 is not None and threshold is not None:
            sample_bits = (sample_stack_u8[:, y, x] >= int(threshold)).astype(np.int16)
            score = float(int(np.sum(sample_bits)) * 2 - int(sample_bits.size))
        else:
            bit = int(candidate_map[y, x]) & 1
            score = 1.0 if bit else -1.0
        if mask_bit_fn(mask_id, x, y):
            score *= -1.0
        cell_scores.append(score)
    logical_scores = []
    for i in range(0, len(cell_scores), repetition):
        logical_scores.append(float(sum(cell_scores[i : i + repetition])))
    return logical_scores


def _try_unpack_candidates(
    *,
    base_scores: Sequence[float],
    header_size_bytes: int,
    unpack_header: Callable[[bytes], T],
    max_uncertain: int = 8,
    max_flips: int = 2,
) -> T:
    last_exc = None
    base_bits = _logical_bits_from_scores(base_scores)
    try:
        return unpack_header(bits_to_bytes(base_bits)[:header_size_bytes])
    except Exception as exc:  # noqa: PERF203
        last_exc = exc

    uncertain = sorted(range(len(base_scores)), key=lambda idx: abs(float(base_scores[idx])))
    max_uncertain = min(max_uncertain, len(uncertain))
    search_space = uncertain[:max_uncertain]
    for flips in range(1, max_flips + 1):
        for combo in combinations(search_space, flips):
            bits = list(base_bits)
            for idx in combo:
                bits[idx] ^= 1
            try:
                return unpack_header(bits_to_bytes(bits)[:header_size_bytes])
            except Exception as exc:  # noqa: PERF203
                last_exc = exc
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("control header unpack failed")


def _aggregate_threshold_scores(
    *,
    sample_stack_u8: np.ndarray,
    thresholds: Sequence[int],
    data_coords: Sequence[Tuple[int, int]],
    header_cell_count: int,
    repetition: int,
    mask_id: int,
    mask_bit_fn: Callable[[int, int, int], int],
) -> List[float]:
    aggregate: np.ndarray | None = None
    for threshold in thresholds:
        logical_scores = _logical_scores_for_map(
            candidate_map=np.zeros((1, 1), dtype=np.uint8),
            sample_stack_u8=sample_stack_u8,
            threshold=int(threshold),
            data_coords=data_coords,
            header_cell_count=header_cell_count,
            repetition=repetition,
            mask_id=mask_id,
            mask_bit_fn=mask_bit_fn,
        )
        arr = np.asarray(logical_scores, dtype=np.float32)
        scale = max(1.0, float(np.mean(np.abs(arr))) if arr.size else 1.0)
        arr = arr / scale
        aggregate = arr if aggregate is None else (aggregate + arr)
    if aggregate is None:
        return []
    return [float(value) for value in aggregate.tolist()]


def decode_binary_control_header(
    *,
    avg_gray_u8: np.ndarray,
    header_maps: Sequence[np.ndarray],
    sample_stack_u8: np.ndarray | None,
    thresholds: Sequence[int],
    data_coords: Sequence[Tuple[int, int]],
    header_size_bytes: int,
    repetition: int,
    mask_id: int,
    mask_bit_fn: Callable[[int, int, int], int],
    unpack_header: Callable[[bytes], T],
) -> T:
    """Decode a repeated binary header from grayscale cell means."""
    header_cell_count = header_size_bytes * 8 * repetition
    if header_cell_count > len(data_coords):
        raise ValueError("header area too small")

    last_exc = None
    candidate_maps: List[np.ndarray] = list(header_maps)
    for threshold in thresholds:
        candidate = (avg_gray_u8 >= int(threshold)).astype(np.uint8)
        if not any(np.array_equal(candidate, existing) for existing in candidate_maps):
            candidate_maps.append(candidate)
        if sample_stack_u8 is not None and sample_stack_u8.ndim == 3 and sample_stack_u8.shape[0] > 0:
            sample_candidate = (
                np.sum(sample_stack_u8 >= int(threshold), axis=0) >= ((sample_stack_u8.shape[0] + 1) // 2)
            ).astype(np.uint8)
            if not any(np.array_equal(sample_candidate, existing) for existing in candidate_maps):
                candidate_maps.append(sample_candidate)

    for candidate_map in candidate_maps:
        logical_scores = _logical_scores_for_map(
            candidate_map=candidate_map,
            sample_stack_u8=sample_stack_u8,
            threshold=None,
            data_coords=data_coords,
            header_cell_count=header_cell_count,
            repetition=repetition,
            mask_id=mask_id,
            mask_bit_fn=mask_bit_fn,
        )
        try:
            return _try_unpack_candidates(
                base_scores=logical_scores,
                header_size_bytes=header_size_bytes,
                unpack_header=unpack_header,
            )
        except Exception as exc:  # noqa: PERF203
            last_exc = exc
    for threshold in thresholds:
        if sample_stack_u8 is None or sample_stack_u8.ndim != 3 or sample_stack_u8.shape[0] == 0:
            continue
        logical_scores = _logical_scores_for_map(
            candidate_map=candidate_maps[0],
            sample_stack_u8=sample_stack_u8,
            threshold=int(threshold),
            data_coords=data_coords,
            header_cell_count=header_cell_count,
            repetition=repetition,
            mask_id=mask_id,
            mask_bit_fn=mask_bit_fn,
        )
        try:
            return _try_unpack_candidates(
                base_scores=logical_scores,
                header_size_bytes=header_size_bytes,
                unpack_header=unpack_header,
            )
        except Exception as exc:  # noqa: PERF203
            last_exc = exc

    if sample_stack_u8 is not None and sample_stack_u8.ndim == 3 and sample_stack_u8.shape[0] > 0 and thresholds:
        aggregate_scores = _aggregate_threshold_scores(
            sample_stack_u8=sample_stack_u8,
            thresholds=thresholds,
            data_coords=data_coords,
            header_cell_count=header_cell_count,
            repetition=repetition,
            mask_id=mask_id,
            mask_bit_fn=mask_bit_fn,
        )
        if aggregate_scores:
            try:
                return _try_unpack_candidates(
                    base_scores=aggregate_scores,
                    header_size_bytes=header_size_bytes,
                    unpack_header=unpack_header,
                    max_uncertain=12,
                    max_flips=3,
                )
            except Exception as exc:  # noqa: PERF203
                last_exc = exc

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("control header decode failed")
