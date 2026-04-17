#!/usr/bin/env python3
"""
Benchmark script to test memory copy performance.

Compares different copy strategies:
1. Original slice-based copy: bgra[:, :, :3]
2. Per-channel copy: separate copies for each channel
3. Memoryview zero-copy: manual BGRA->RGB conversion
"""

import time

import numpy as np


def benchmark_slice_copy(bgra: np.ndarray, dst: np.ndarray, iterations: int = 100) -> float:
    """Original slice-based copy."""
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        dst[...] = bgra[:, :, :3]
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000.0)
    return sum(times) / len(times)


def benchmark_channel_copy(bgra: np.ndarray, dst: np.ndarray, iterations: int = 100) -> float:
    """Per-channel copy."""
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        dst[:, :, 0] = bgra[:, :, 0]
        dst[:, :, 1] = bgra[:, :, 1]
        dst[:, :, 2] = bgra[:, :, 2]
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000.0)
    return sum(times) / len(times)


def benchmark_rgba_zero_copy(
    bgra_bytes: bytes, dst: np.ndarray, width: int, height: int, iterations: int = 100
) -> float:
    """RGBA zero-copy (used in implementation)."""
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        bgra = np.frombuffer(bgra_bytes, dtype=np.uint8).reshape((height, width, 4))
        dst[...] = bgra  # Direct copy, all 4 channels
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000.0)
    return sum(times) / len(times)


def benchmark_fast_numpy_copy(
    bgra_bytes: bytes, dst: np.ndarray, width: int, height: int, iterations: int = 100
) -> float:
    """Fast numpy-based BGRA->RGB copy."""
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        bgra = np.frombuffer(bgra_bytes, dtype=np.uint8).reshape((height, width, 4))
        dst[:, :, 0] = bgra[:, :, 2]  # R
        dst[:, :, 1] = bgra[:, :, 1]  # G
        dst[:, :, 2] = bgra[:, :, 0]  # B
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000.0)
    return sum(times) / len(times)


def benchmark_memoryview_copy(
    bgra_bytes: bytes, dst: np.ndarray, width: int, height: int, iterations: int = 100
) -> float:
    """Memoryview zero-copy (slow Python loop)."""
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        src_mv = memoryview(bgra_bytes).cast("B")
        dst_mv = memoryview(dst).cast("B")

        src_idx = 0
        dst_idx = 0
        total_pixels = width * height

        for _ in range(total_pixels):
            dst_mv[dst_idx] = src_mv[src_idx + 2]  # R
            dst_mv[dst_idx + 1] = src_mv[src_idx + 1]  # G
            dst_mv[dst_idx + 2] = src_mv[src_idx]  # B
            src_idx += 4
            dst_idx += 3

        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000.0)
    return sum(times) / len(times)


def main():
    # Test with typical screen resolution
    width, height = 1920, 1080
    print(f"Testing with resolution: {width}x{height}")
    print(f"Frame size: {width * height * 4 / 1024 / 1024:.2f} MB (BGRA)")
    print()

    # Create test data
    bgra = np.random.randint(0, 256, (height, width, 4), dtype=np.uint8)
    bgra_bytes = bytes(bgra.tobytes())
    dst_rgb = np.empty((height, width, 3), dtype=np.uint8)
    dst_rgba = np.empty((height, width, 4), dtype=np.uint8)

    # Warmup
    for _ in range(10):
        dst_rgb[...] = bgra[:, :, :3]

    # Benchmark
    iterations = 50
    print(f"Running {iterations} iterations for each method...\n")

    slice_time = benchmark_slice_copy(bgra, dst_rgb, iterations)
    channel_time = benchmark_channel_copy(bgra, dst_rgb, iterations)
    fast_numpy_time = benchmark_fast_numpy_copy(bgra_bytes, dst_rgb, width, height, iterations)
    rgba_time = benchmark_rgba_zero_copy(bgra_bytes, dst_rgba, width, height, iterations)
    memview_time = benchmark_memoryview_copy(bgra_bytes, dst_rgb, width, height, iterations)

    # Calculate bandwidth
    frame_mb_rgb = width * height * 3 / 1024 / 1024
    frame_mb_rgba = width * height * 4 / 1024 / 1024
    slice_bw = frame_mb_rgb / (slice_time / 1000.0)
    channel_bw = frame_mb_rgb / (channel_time / 1000.0)
    fast_numpy_bw = frame_mb_rgb / (fast_numpy_time / 1000.0)
    rgba_bw = frame_mb_rgba / (rgba_time / 1000.0)
    memview_bw = frame_mb_rgb / (memview_time / 1000.0)

    print("Results:")
    print("-" * 70)
    print(f"{'Method':<30} {'Time (ms)':<15} {'Bandwidth (GB/s)':<20} {'Speedup'}")
    print("-" * 70)
    print(
        f"{'Slice copy (original)':<30} {slice_time:>10.2f} ms   {slice_bw / 1024:>10.2f} GB/s   {1.0:>6.2f}x"
    )
    print(
        f"{'Per-channel copy':<30} {channel_time:>10.2f} ms   {channel_bw / 1024:>10.2f} GB/s   {slice_time / channel_time:>6.2f}x"
    )
    print(
        f"{'Fast numpy copy':<30} {fast_numpy_time:>10.2f} ms   {fast_numpy_bw / 1024:>10.2f} GB/s   {slice_time / fast_numpy_time:>6.2f}x"
    )
    print(
        f"{'RGBA zero-copy (used)':<30} {rgba_time:>10.2f} ms   {rgba_bw / 1024:>10.2f} GB/s   {slice_time / rgba_time:>6.2f}x"
    )
    print(
        f"{'Memoryview (Python loop)':<30} {memview_time:>10.2f} ms   {memview_bw / 1024:>10.2f} GB/s   {slice_time / memview_time:>6.2f}x"
    )
    print("-" * 70)
    print()

    # Calculate theoretical max FPS
    grab_time = 17.0  # ms (typical MSS grab time)
    print("Theoretical max FPS (assuming 17ms grab time):")
    print(f"  Original:   {1000.0 / (grab_time + slice_time):.1f} fps")
    print(f"  Channel:    {1000.0 / (grab_time + channel_time):.1f} fps")
    print(f"  Fast numpy: {1000.0 / (grab_time + fast_numpy_time):.1f} fps")
    print(f"  RGBA:       {1000.0 / (grab_time + rgba_time):.1f} fps")
    print(f"  Async copy: {1000.0 / grab_time:.1f} fps (copy in parallel)")


if __name__ == "__main__":
    main()
