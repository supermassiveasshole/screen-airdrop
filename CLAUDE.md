# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

# Run tests by marker
uv run pytest -m "not real_data and not regression_data"

# Lint
uv run ruff check src tests
uv run ruff format src tests

# Type check
uv run pyright

# Run sender (modern)
uv run screen-airdrop-sender ./path/to/input --window-name "screen-airdrop"

# Run receiver
uv run screen-airdrop-receiver --source screen --window-title "Remote Desktop" --output-dir ./recovered

# Benchmark
uv run python bench/run_benchmark.py --mode replay --quick
uv run python bench/summarize.py
```

## Architecture

### Package layout (`src/screen_airdrop/`)

- **`common/`** — shared code that must stay Python 3.7 compatible:
  - `protocol.py` — V1/V2 binary frame header struct, CRC, magic bytes (`SARD`)
  - `protocol_v3.py` — V3 frame header, ECC level definitions (`SAR3`)
  - `layout_v31.py` — V3.1 `LayoutInfoV31` dataclass (four-corner fixed-grid contract)
  - `manifest.py` — session manifest (JSON: file list, SHA-256, chunk params)
  - `packing.py` — tar/gzip pack and unpack helpers
  - `errors.py` — typed error codes (E1001–E3002)

- **`sender/`** — encodes and plays frames on screen:
  - `modern.py` / `legacy.py` — CLI entrypoints; legacy targets Python 3.7.6 with stdlib only
  - `controller.py` — orchestrates pack → encode → render loop
  - `encoder.py` / `encoder_v3.py` / `encoder_v31.py` — protocol-specific frame renderers
  - `renderer_cv2.py` — OpenCV window display loop

- **`receiver/`** — captures screen and reconstructs files:
  - `cli.py` — unified receiver CLI (handles v1/v2/v3/v3_1)
  - `capture_mss.py` — MSS screen capture
  - `locator.py` / `locator_v31.py` — window/frame locator (v2: contour detection; v3.1: four-corner finder patterns)
  - `detector_v3.py` / `detector_v31.py` — symbol bounding box detection
  - `decoder.py` / `decoder_v3.py` / `decoder_v31.py` — grid sampling → bits → frame header + payload
  - `assembler.py` — chunk deduplication and completion tracking
  - `restore.py` — reassemble payload, decompress, SHA-256 verify
  - `stats.py` — real-time throughput/FPS/ETA metrics
  - `roi_selector.py` / `roi_profile.py` — interactive region selection and persistence
  - `frame_replay_source.py` — replay pre-captured frames for offline testing

### Protocol versions

| Protocol | Magic | Key feature |
|----------|-------|-------------|
| v1/v2 | `SARD` | Contour-based locator, block grid payload |
| v3 | `SAR3` | QR-style finder patterns + timing strips, ECC repetition |
| v3_1 | `SAR3` | Four-corner fixed-grid, module-center sampling, `LayoutInfoV31` embedded in sync frame |

The default protocol is **v3_1**. The receiver `--locator-engine auto` tries the new locator first, falls back to legacy. `v3_1` does not fall back to `v3` decoding.

### Python version constraints

- `src/screen_airdrop/common/**` and `src/screen_airdrop/sender/**` must be Python 3.7 compatible (enforced by `ruff.per-file-target-version`)
- Receiver and dev tooling require Python 3.10+
- Ruff `target-version = "py312"` applies to everything except the above overrides

### Tests

- `tests/unit/` — pure logic tests, no hardware needed
- `tests/integration/` — loopback and lossy frame pipeline tests
- `tests/e2e/` — real captured frame datasets (marker: `real_data`, `regression_data`)
- Fixtures with real frame data live in `tests/fixtures/real_data/`
