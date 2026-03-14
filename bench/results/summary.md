# Benchmark Summary

## Synthetic CPU

| file | protocol | ecc | payload_mode | success_rate | synthetic_cpu_kib_per_s |
|---|---|---|---|---:|---:|
| synthetic_cpu_benchmark_1772969402.json | basic | L | fixed | 1.00 | 1.10 |
| synthetic_cpu_benchmark_1772969402.json | basic | M | fixed | 1.00 | 1.32 |
| synthetic_cpu_benchmark_1772969402.json | basic | Q | fixed | 1.00 | 3.07 |
| synthetic_cpu_benchmark_1772969402.json | basic | H | fixed | 1.00 | 1.00 |
| synthetic_cpu_benchmark_1772969402.json | compact | L | fixed | 1.00 | 4.36 |
| synthetic_cpu_benchmark_1772969402.json | compact | M | fixed | 1.00 | 3.48 |
| synthetic_cpu_benchmark_1772969402.json | compact | Q | fixed | 1.00 | 4.16 |
| synthetic_cpu_benchmark_1772969402.json | compact | H | fixed | 1.00 | 3.34 |
| synthetic_cpu_benchmark_1772969448.json | basic | L | fixed | 1.00 | 1.16 |
| synthetic_cpu_benchmark_1772969448.json | basic | M | fixed | 1.00 | 1.25 |
| synthetic_cpu_benchmark_1772969448.json | basic | Q | fixed | 1.00 | 3.11 |
| synthetic_cpu_benchmark_1772969448.json | basic | H | fixed | 1.00 | 1.01 |
| synthetic_cpu_benchmark_1772969448.json | compact | L | fixed | 1.00 | 4.21 |
| synthetic_cpu_benchmark_1772969448.json | compact | M | fixed | 1.00 | 4.22 |
| synthetic_cpu_benchmark_1772969448.json | compact | Q | fixed | 1.00 | 4.13 |
| synthetic_cpu_benchmark_1772969448.json | compact | H | fixed | 1.00 | 3.45 |
| synthetic_cpu_benchmark_1772969637.json | basic | Q | max | 1.00 | 1.84 |
| synthetic_cpu_benchmark_1772969637.json | compact | Q | max | 1.00 | 3.33 |
| synthetic_cpu_benchmark_1772969874.json | basic | L | max | 1.00 | 3.75 |
| synthetic_cpu_benchmark_1772969874.json | basic | M | max | 1.00 | 2.28 |
| synthetic_cpu_benchmark_1772969874.json | basic | Q | max | 1.00 | 3.51 |
| synthetic_cpu_benchmark_1772969874.json | basic | H | max | 1.00 | 1.17 |
| synthetic_cpu_benchmark_1772969874.json | compact | L | max | 1.00 | 17.13 |
| synthetic_cpu_benchmark_1772969874.json | compact | M | max | 1.00 | 8.13 |
| synthetic_cpu_benchmark_1772969874.json | compact | Q | max | 1.00 | 5.44 |
| synthetic_cpu_benchmark_1772969874.json | compact | H | max | 1.00 | 3.95 |
| synthetic_cpu_benchmark_1772971745.json | basic | Q | max | 1.00 | 2.70 |
| synthetic_cpu_benchmark_1772971745.json | compact | Q | max | 1.00 | 4.18 |

## Real-frame Decode

| file | protocol | dataset | success_rate | locator_decode_ms_avg | locator_engine_breakdown |
|---|---|---|---:|---:|---|
| real_frame_decode_benchmark_1772969339.json | basic | basic_regression | 1.00 | 221.62 | `{"new": 5}` |
| real_frame_decode_benchmark_1772969339.json | compact | compact | 1.00 | 118.11 | `{"corner": 5}` |
| real_frame_decode_benchmark_1772969339.json | compact | compact_v4 | 1.00 | 91.86 | `{"corner": 5}` |
| real_frame_decode_benchmark_1772969440.json | basic | basic_regression | 1.00 | 182.88 | `{"new": 5}` |
| real_frame_decode_benchmark_1772969440.json | compact | compact | 1.00 | 92.89 | `{"corner": 5}` |
| real_frame_decode_benchmark_1772969440.json | compact | compact_v4 | 1.00 | 88.05 | `{"corner": 5}` |

## End-to-End Replay

| file | protocol | ecc | payload_mode | payload_bytes | rx_payload_kib_per_s | status |
|---|---|---|---|---:|---:|---|
| end_to_end_replay_benchmark_1772969343.json | basic | Q | fixed | 500 | 0.59 | ok |
| end_to_end_replay_benchmark_1772969343.json | compact | Q | fixed | 500 | 0.79 | ok |
| end_to_end_replay_benchmark_1772969641.json | basic | Q | max | 536 | 0.68 | ok |
| end_to_end_replay_benchmark_1772969641.json | compact | Q | max | 536 | 1.05 | ok |

## End-to-End Screen Runbook

| file | protocol | ecc | payload_mode | payload_bytes | rx_payload_kib_per_s | status |
|---|---|---|---|---:|---:|---|
| end_to_end_screen_benchmark_1772969392.json | basic | Q | max | 536 | 0.00 | runbook |
| end_to_end_screen_benchmark_1772969392.json | compact | Q | max | 536 | 0.00 | runbook |
| end_to_end_screen_benchmark_1772969437.json | basic | Q | max | 536 | 0.00 | runbook |
| end_to_end_screen_benchmark_1772969437.json | compact | Q | max | 536 | 0.00 | runbook |
| end_to_end_screen_benchmark_1772969861.json | basic | Q | fixed | 500 | 0.00 | runbook |
| end_to_end_screen_benchmark_1772969861.json | compact | Q | fixed | 500 | 0.00 | runbook |
| end_to_end_screen_benchmark_1772969944.json | basic | Q | max | 536 | 0.00 | runbook |
| end_to_end_screen_benchmark_1772969944.json | compact | Q | max | 536 | 0.00 | runbook |
| end_to_end_screen_benchmark_1772970805.json | basic | Q | max | 536 | 0.00 | runbook |
| end_to_end_screen_benchmark_1772970805.json | compact | Q | max | 536 | 0.00 | runbook |
| end_to_end_screen_benchmark_1772971682.json | basic | Q | max | 536 | 0.00 | runbook |
| end_to_end_screen_benchmark_1772971682.json | compact | Q | max | 594 | 0.00 | runbook |
| end_to_end_screen_benchmark_1772971743.json | basic | Q | max | 536 | 0.00 | runbook |
| end_to_end_screen_benchmark_1772971743.json | compact | Q | max | 594 | 0.00 | runbook |

