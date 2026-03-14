# Benchmark Status

## Scope

This document records the current benchmark stack and the latest comparable results for `basic` vs `compact`.

The benchmark system is intentionally split into three layers:

1. `Synthetic CPU`
- Measures local encode/decode CPU cost only.
- Does not include capture, window rendering, or end-to-end transfer.

2. `Real-frame decode`
- Measures `locator + decode` cost and success rate on real captured `raw.png` frames.
- Does not include screen capture cost.

3. `End-to-end replay / screen`
- Measures effective transfer behavior through the existing sender/receiver stack.
- `replay` is fully automated.
- `screen` generates a controlled runbook for manual local-screen testing.
- The benchmark target is **transfer rate over a fixed time window**, not full completion.

For large real inputs, the full-transfer-oriented replay path can still be a poor fit for rapid parameter scans. The recommended first-pass scanner for single-window tuning is now:

4. `Sampled frame decode success`
- Uses deterministic small sample payloads sized to a fixed number of chunks.
- Avoids materializing huge replay frame sequences for large source files.
- Prioritizes:
  - `decode_success_rate`
  - `locator_fail_rate`
  - `bad_frame_rate`
- Treats goodput as secondary during the first filter pass.

## Current Benchmark Tools

- `bench/compare_protocols.py`
  - Synthetic encode/decode CPU microbenchmark.
  - Supports:
    - `--protocol basic|compact|all`
    - `--ecc L|M|Q|H|all`
    - `--payload-mode fixed|max`

- `bench/compare_decode_real.py`
  - Real-frame `locator + decode` benchmark.
  - Uses:
    - `basic`: `tests/fixtures/v31_regression_cases.json`
    - `compact`: `debug/compact/*.raw.png`, `debug/compact_v4/*.raw.png`

- `bench/compare_end_to_end.py`
  - `--mode replay`: automated end-to-end benchmark.
  - `--mode screen`: controlled local-screen runbook generator.

- `bench/scan_frame_decode_success.py`
  - recommended first-pass single-window scanner
  - generates deterministic small sample files sized to `sample_chunks * effective_chunk_size`
  - scans:
    - display mode
    - explicit compact grids
    - payload ratios
  - current default scan is intentionally aggressive:
    - `display_mode=fullscreen`
    - grids: `180x110,192x118,208x128,224x136,240x144`
    - payload ratios: `0.90,0.95,0.98,1.00`
    - `sample_chunks=32`
  - uses replay only as a cheap filter
  - writes:
    - JSON result under `bench/results/`
    - markdown status to [frame_decode_success_status.md](/Users/waldron/Code/screen-airdrop/docs/frame_decode_success_status.md)

- `bench/summarize.py`
  - Aggregates JSON results into `bench/results/summary.md`.

## Reliability Gate

The current regression matrix now requires:

- `basic` synthetic self-roundtrip: `L/M/Q/H` all pass
- `compact` synthetic self-roundtrip: `L/M/Q/H` all pass
- `basic` real regression dataset: pass
- `compact` real datasets: pass

This avoids benchmarking on a broken ECC path.

## Latest Results

### 1. Synthetic CPU, fixed payload
Reference dataset:
- `bench/results/synthetic_cpu_benchmark_1772969448.json`

At `payload_mode=fixed`, `payload_bytes=500`:
- `basic(Q)`: about `3.11 KiB/s`
- `compact(Q)`: about `4.13 KiB/s`

At fixed payload, `compact` is faster mainly because its decode path is cheaper.

### 2. Synthetic CPU, max payload
Reference dataset:
- `bench/results/synthetic_cpu_benchmark_1772969874.json`

At `payload_mode=max`:

- `basic`
  - `L`: `1688 B`, `3.75 KiB/s`
  - `M`: `824 B`, `2.28 KiB/s`
  - `Q`: `536 B`, `3.51 KiB/s`
  - `H`: `392 B`, `1.17 KiB/s`

- `compact`
  - `L`: `1688 B`, `17.13 KiB/s`
  - `M`: `824 B`, `8.13 KiB/s`
  - `Q`: `536 B`, `5.44 KiB/s`
  - `H`: `392 B`, `3.95 KiB/s`

Synthetic conclusion:
- `compact` currently dominates `basic` on local CPU microbenchmark cost across all ECC levels.
- This is still not a real throughput claim.

### 3. Real-frame decode
Reference dataset:
- `bench/results/real_frame_decode_benchmark_1772969440.json`

Results:
- `basic / basic_regression`
  - success rate: `1.00`
  - `locator+decode`: about `182.88 ms`
  - locator: `new`

- `compact / compact`
  - success rate: `1.00`
  - `locator+decode`: about `92.89 ms`
  - locator: `corner`

- `compact / compact_v4`
  - success rate: `1.00`
  - `locator+decode`: about `88.05 ms`
  - locator: `corner`

Real-frame decode conclusion:
- On current captured datasets, `compact` decodes materially faster than `basic`.
- The `compact_v4` samples that previously failed are now part of regression and pass.

### 4. End-to-end replay
Reference datasets:
- `bench/results/end_to_end_replay_benchmark_1772969343.json`
- `bench/results/end_to_end_replay_benchmark_1772969641.json`

#### Fixed payload (`500 B`, `Q`)
- `basic`: `rx_payload_kib_per_s ≈ 0.59`
- `compact`: `rx_payload_kib_per_s ≈ 0.79`

#### Max payload (`536 B`, `Q`)
- `basic`: `rx_payload_kib_per_s ≈ 0.68`
- `compact`: `rx_payload_kib_per_s ≈ 1.05`

Replay conclusion:
- Under the current automated replay harness, `compact` outperforms `basic` in effective receive-side payload rate.
- In the `Q + max payload` replay result, `compact` improves receive-side payload rate by roughly `54%` over `basic`.

### 5. Observed local-screen benchmark (`Q`, footprint-matched, 30s)

Observed from real local-screen runs with:

- `basic`: `160x96`, `536 B`
- `compact`: `166x102`, `594 B`
- `fps=12`
- `capture_fps=30`
- manual ROI
- `max-seconds=30`

Payload-density difference:

- `basic`: `536 B/frame`
- `compact`: `594 B/frame`
- payload ratio: `594 / 536 ≈ 1.108`

Receiver-side steady-state rate from the captured logs:

- `basic`: about `5.96 KB/s` average over steady-state windows
- `compact`: about `6.88 KB/s` average over steady-state windows

Observed local-screen conclusion:

- `compact` improves steady-state receive-side payload rate by roughly `15.4%`
- `compact` also reduces total missing chunks because each successfully decoded frame carries more payload
- in the observed run, `compact` retained comparable capture/decode stability while increasing effective information per frame

## Current Interpretation

The current evidence supports these narrower claims:

1. `compact` is cheaper than `basic` in synthetic encode/decode CPU cost.
2. `compact` is faster than `basic` on current real-frame `locator + decode` datasets.
3. `compact` is better than `basic` in the current replay end-to-end benchmark.

The current evidence does **not** yet prove:

1. `compact` is better than `basic` on real local-screen end-to-end throughput.
2. `compact` remains better under VNC / remote desktop degradation.
3. `compact` improves throughput because of higher net information density alone.

Those claims still require screen-mode runs and additional controlled measurements.
The current observed local-screen run already supports a stronger claim than before:

4. under the footprint-matched local-screen benchmark, `compact` is better than `basic` in steady-state receive-side payload rate.

## Important Limitation Of The Old `max payload` Comparison

The older `max payload` comparison using:

- `basic`: `160x96`
- `compact`: `160x96`

does **not** demonstrate `compact`'s payload-density advantage.

It only demonstrates:
- protocol-safe max chunk size under the current identical data-grid size
- and decode/runtime cost differences

Under the same `160x96` grid, both protocols currently land on nearly the same safe payload cap in `Q`, so that comparison is still useful for runtime cost, but not for net information density.

To expose payload advantage, the correct comparison is:

- keep the **outer display footprint** fixed to the `basic 160x96` baseline
- let `compact` spend its saved finder/guard overhead on a larger data grid

The first practical footprint-matched benchmark is:

- `basic`: `160x96`
- `compact`: `166x102`

Under this equal-footprint benchmark, the current protocol-safe max payload becomes:

- `basic(Q)`: `536 B`
- `compact(Q)`: `594 B`

## Controlled Screen Benchmark Commands

These commands are rate-benchmark runbooks. They use a larger PDF payload and force the receiver to stop after a fixed time window.

### Fixed payload (`Q`, `500 B`)

`basic` sender:
```bash
uv run screen-airdrop-sender /Users/waldron/Code/screen-airdrop/tests/fixtures/real_data/regular_pdf --protocol basic --module-grid 160x96 --ecc-level Q --fps 12 --chunk-size 500 --stats-interval 1.0
```

`basic` receiver:
```bash
uv run screen-airdrop-receiver --source screen --protocol basic --module-grid 160x96 --roi-interactive --capture-fps 30 --stats-interval 1.0 --max-seconds 30 --output-dir ./recovered_basic_Q_fixed
```

`compact` sender:
```bash
uv run screen-airdrop-sender /Users/waldron/Code/screen-airdrop/tests/fixtures/real_data/regular_pdf --protocol compact --module-grid 160x96 --ecc-level Q --fps 12 --chunk-size 500 --stats-interval 1.0
```

`compact` receiver:
```bash
uv run screen-airdrop-receiver --source screen --protocol compact --module-grid 160x96 --roi-interactive --capture-fps 30 --stats-interval 1.0 --max-seconds 30 --output-dir ./recovered_compact_Q_fixed
```

### Max payload (`Q`, protocol-safe)

`basic` sender:
```bash
uv run screen-airdrop-sender /Users/waldron/Code/screen-airdrop/tests/fixtures/real_data/regular_pdf --protocol basic --module-grid 160x96 --ecc-level Q --fps 12 --chunk-size 536 --stats-interval 1.0
```

`basic` receiver:
```bash
uv run screen-airdrop-receiver --source screen --protocol basic --module-grid 160x96 --roi-interactive --capture-fps 30 --stats-interval 1.0 --max-seconds 30 --output-dir ./recovered_basic_Q_max
```

`compact` sender:
```bash
uv run screen-airdrop-sender /Users/waldron/Code/screen-airdrop/tests/fixtures/real_data/regular_pdf --protocol compact --module-grid 160x96 --ecc-level Q --fps 12 --chunk-size 536 --stats-interval 1.0
```

`compact` receiver:
```bash
uv run screen-airdrop-receiver --source screen --protocol compact --module-grid 160x96 --roi-interactive --capture-fps 30 --stats-interval 1.0 --max-seconds 30 --output-dir ./recovered_compact_Q_max
```

### Max payload, footprint-matched (`Q`, equal display footprint)

`basic` sender:
```bash
uv run screen-airdrop-sender /Users/waldron/Code/screen-airdrop/tests/fixtures/real_data/regular_pdf --protocol basic --module-grid 160x96 --ecc-level Q --fps 12 --chunk-size 536 --stats-interval 1.0
```

`basic` receiver:
```bash
uv run screen-airdrop-receiver --source screen --protocol basic --module-grid 160x96 --roi-interactive --capture-fps 30 --stats-interval 1.0 --max-seconds 30 --output-dir ./recovered_basic_Q_max
```

`compact` sender:
```bash
uv run screen-airdrop-sender /Users/waldron/Code/screen-airdrop/tests/fixtures/real_data/regular_pdf --protocol compact --module-grid 166x102 --ecc-level Q --fps 12 --chunk-size 594 --stats-interval 1.0
```

`compact` receiver:
```bash
uv run screen-airdrop-receiver --source screen --protocol compact --module-grid 166x102 --roi-interactive --capture-fps 30 --stats-interval 1.0 --max-seconds 30 --output-dir ./recovered_compact_Q_max
```

## Next Decisions

The next useful step is not more synthetic work. It is:

1. Run the fixed-payload screen comparison.
2. Run the max-payload screen comparison.
3. Record sender and receiver logs for both protocols.
4. Compare:
   - `cap_fps`
   - `dec_fps`
   - `rx_KBps`
   - recovery time
   - failure rate

Only after that should we promote `compact` performance claims beyond replay and real-frame decode.
