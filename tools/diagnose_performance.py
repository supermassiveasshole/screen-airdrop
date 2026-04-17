#!/usr/bin/env python3
"""Performance diagnostic script for screen-airdrop receiver.

This script helps diagnose performance issues by:
1. Measuring MSS capture performance
2. Checking system resource usage
3. Profiling memory allocation
"""

import time

import mss
import numpy as np
import psutil


def measure_mss_performance(iterations=100):
    """Measure MSS screen capture performance."""
    print("=== MSS Capture Performance ===")

    with mss.mss() as sct:
        # Get primary monitor
        monitor = sct.monitors[1]
        print(f"Monitor: {monitor['width']}x{monitor['height']}")

        # Warmup
        for _ in range(10):
            sct.grab(monitor)

        # Measure
        times = []
        for _ in range(iterations):
            t0 = time.perf_counter()
            shot = sct.grab(monitor)
            t1 = time.perf_counter()
            times.append((t1 - t0) * 1000.0)

            # Convert to numpy (this is what the receiver does)
            bgra = np.asarray(shot)
            rgb = bgra[:, :, :3]

        avg_ms = sum(times) / len(times)
        min_ms = min(times)
        max_ms = max(times)
        p50_ms = sorted(times)[len(times) // 2]
        p95_ms = sorted(times)[int(len(times) * 0.95)]

        print(f"Iterations: {iterations}")
        print(f"Average: {avg_ms:.2f}ms")
        print(f"Min: {min_ms:.2f}ms")
        print(f"Max: {max_ms:.2f}ms")
        print(f"P50: {p50_ms:.2f}ms")
        print(f"P95: {p95_ms:.2f}ms")
        print(f"Theoretical max FPS: {1000.0 / avg_ms:.1f}")
        print()


def check_system_resources():
    """Check system resource usage."""
    print("=== System Resources ===")

    # CPU
    cpu_percent = psutil.cpu_percent(interval=1.0)
    cpu_count = psutil.cpu_count()
    print(f"CPU: {cpu_percent}% ({cpu_count} cores)")

    # Memory
    mem = psutil.virtual_memory()
    print(f"Memory: {mem.percent}% used ({mem.used / 1024**3:.1f}GB / {mem.total / 1024**3:.1f}GB)")

    # Swap
    swap = psutil.swap_memory()
    if swap.total > 0:
        print(f"Swap: {swap.percent}% used ({swap.used / 1024**3:.1f}GB / {swap.total / 1024**3:.1f}GB)")

    print()


def check_python_process():
    """Check current Python process resource usage."""
    print("=== Python Process ===")

    process = psutil.Process()

    # Memory
    mem_info = process.memory_info()
    print(f"RSS: {mem_info.rss / 1024**2:.1f}MB")
    print(f"VMS: {mem_info.vms / 1024**2:.1f}MB")

    # CPU
    cpu_percent = process.cpu_percent(interval=1.0)
    print(f"CPU: {cpu_percent}%")

    # Threads
    num_threads = process.num_threads()
    print(f"Threads: {num_threads}")

    print()


if __name__ == "__main__":
    print("Screen-Airdrop Performance Diagnostic")
    print("=" * 50)
    print()

    check_system_resources()
    check_python_process()
    measure_mss_performance(iterations=100)

    print("=" * 50)
    print("Diagnostic complete.")
    print()
    print("If grab_ms is consistently > 15ms, possible causes:")
    print("1. High system load (check CPU/Memory above)")
    print("2. Large window size (check Monitor dimensions)")
    print("3. Other processes competing for resources")
    print("4. Display scaling/resolution issues")
