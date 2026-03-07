# CONFIG.md

This file provides guidance to Assistant (ai.ai/code) when working with code in this repository.

## What this project is

`screen-airdrop` transfers files from an air-gapped/isolated server to a local machine by encoding data as visual frames displayed in a remote desktop window, which the local receiver captures and decodes via screen capture. No shared drives, clipboard, or network channels are used.

## Commands

```bash
# Install all dev dependencies
uv sync --group dev

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/unit/test_protocol.py

# Run tests excluding real hardware/dataset markers
uv run pytest -m "not real_data and not regression_data"

# Lint and format
uv run ruff check src tests
uv run ruff format src tests

# Type check
uv run pyright

# Run sender (modern)
uv run screen-airdrop-sender ./path/to/input --window-name "screen-airdrop"

# Run receiver
uv run screen-airdrop-receiver --source screen --window-title "Remote Desktop" --output-dir ./recovered

# Benchmark (quick replay mode)
uv run python bench/run_benchmark.py --mode replay --quick
uv run python bench/summarize.py

# Build offline wheelhouse and CentOS 7 onefile sender
./scripts/build_wheelhouse.sh
./scripts/build_centos7_sender.sh
```

## Architecture

### Package layout (`src/screen_airdrop/`)

- **`common/`** — shared code; **must remain Python 3.7 compatible**:
  - `protocol_basic.py` — basic protocol frame header, ECC level definitions (`SAR3`)
  - `layout_basic.py` — `LayoutInfoBasic` dataclass: four-corner fixed-grid contract
  - `manifest.py` — session manifest (JSON: file list, SHA-256, chunk params)
  - `packing.py` — tar/gzip pack and unpack helpers
  - `errors.py` — typed error codes (E1001–E3002)

- **`sender/`** — encodes and plays frames on screen; **must remain Python 3.7 compatible**:
  - `modern.py` / `legacy.py` — CLI entrypoints; `legacy` targets Python 3.7.6 with stdlib only
  - `controller.py` — orchestrates pack → encode → render loop
  - `encoder_basic.py` — basic protocol frame renderer
  - `renderer_cv2.py` — OpenCV window display loop
  - `runtime_compat.py` — cross-version shims

- **`receiver/`** — captures screen and reconstructs files (Python 3.10+ required):
  - `cli.py` — unified receiver CLI
  - `pipeline.py` — **core coordinator**: multi-threaded producer-consumer pipeline (see below)
  - `capture_mss.py` — MSS screen capture + frame dedup via pixel diff
  - `locator_basic.py` — four-corner finder patterns locator
  - `detector_basic.py` / `detector_v31_basic.py` — symbol bounding-box detection
  - `decoder_basic.py` — grid sampling → bits → frame header + payload
  - `assembler.py` — chunk deduplication and completion tracking
  - `restore.py` — reassemble payload, decompress, SHA-256 verify
  - `stats.py` — real-time throughput/FPS/ETA metrics
  - `roi_selector.py` / `roi_profile.py` — interactive region selection and persistence
  - `frame_replay_source.py` — replay pre-captured frames for offline testing
  - `window_locator.py` — window resolution helpers

### Receiver pipeline threading model

`pipeline.py` wires three thread layers:

1. **`CaptureThread`** — grabs frames from MSS at `target_fps`, skips duplicates via pixel-diff threshold, pushes into `frame_queue`.
2. **`DecodeWorker` × N** — pops from `frame_queue`, calls `decode_frame_v31`, maintains per-worker ROI tracking state (resets to `initial_search_roi` on failure), pushes `DecodeResult` into `result_queue`. `N` defaults to `min(4, cpu_count // 2)`.
3. **`AssemblerThread`** — pops `DecodeResult`, feeds `ChunkAssembler`, fires `done_event` when all chunks received.

Queue sizes: `frame_queue=32` (drops oldest on overflow), `result_queue=256`.

### Protocol

The current protocol is **basic** (magic bytes: `SAR3`). It uses four-corner fixed-grid, module-center sampling, and `LayoutInfoBasic` embedded in sync frames. A future **fountain** (喷泉码) protocol is planned.

### Python version constraints

- `src/screen_airdrop/common/**` and `src/screen_airdrop/sender/**` must be Python 3.7 compatible (enforced by `ruff.per-file-target-version = "py37"`).
- Receiver and dev tooling require Python 3.10+.
- Global `ruff target-version = "py312"` applies everywhere except the above overrides.

### Tests

- `tests/unit/` — pure logic tests, no hardware needed
- `tests/integration/` — loopback and lossy frame pipeline tests
- `tests/e2e/` — real captured frame datasets (markers: `real_data`, `regression_data`)
- Real frame fixtures live in `tests/fixtures/real_data/`

### Key benchmark metrics

- `goodput_kibps` — effective payload throughput (KiB/s); primary performance indicator
- `raw_frame_rate_fps` — total frame rate including bad frames
- `valid_frame_rate_fps` — CRC/decode-passing frame rate
- `bad_frame_rate` — fraction of bad frames
- `fallback_ratio` — fraction of frames that fell back to legacy v3 decoder
- `homography_stability` — mean inter-frame detection jitter (lower = more stable)
