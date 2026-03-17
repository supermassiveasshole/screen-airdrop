# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

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
uv run python bench/compare_protocols.py --protocol all --ecc Q --payload-mode fixed --payload-size 500
uv run python bench/compare_decode_real.py --protocol all --iterations 15
uv run python bench/compare_end_to_end.py --mode replay --protocol all --ecc Q --payload-mode fixed --payload-size 500
uv run python bench/summarize.py
```

## Architecture

### Package layout (`src/screen_airdrop/`)

- **`common/`** — shared code that must stay Python 3.7 compatible:
  - `protocol_basic.py` — basic protocol frame header, ECC level definitions (`SAR3`)
  - `layout_basic.py` — `LayoutInfoBasic` dataclass (four-corner fixed-grid contract)
  - `manifest.py` — session manifest (JSON: file list, SHA-256, chunk params)
  - `packing.py` — tar/gzip pack and unpack helpers
  - `errors.py` — typed error codes (E1001–E3002)

- **`sender/`** — encodes and plays frames on screen:
  - `modern.py` / `legacy.py` — CLI entrypoints; legacy targets Python 3.7.6 with stdlib only
  - `controller.py` — orchestrates pack → encode → render loop
  - `encoder_basic.py` — basic protocol frame renderer
  - `renderer_cv2.py` — OpenCV window display loop

- **`receiver/`** — captures screen and reconstructs files:
  - `cli.py` — unified receiver CLI
  - `capture_mss.py` — MSS screen capture
  - `locator_basic.py` — four-corner finder patterns locator
  - `detector_basic.py` / `detector_v31_basic.py` — symbol bounding box detection
  - `decoder_basic.py` — grid sampling → bits → frame header + payload
  - `assembler.py` — chunk deduplication and completion tracking
  - `restore.py` — reassemble payload, decompress, SHA-256 verify
  - `stats.py` — real-time throughput/FPS/ETA metrics
  - `roi_selector.py` / `roi_profile.py` — interactive region selection and persistence
  - `frame_replay_source.py` — replay pre-captured frames for offline testing

### Protocol

The current protocol is **basic** (magic bytes: `SAR3`). It uses four-corner fixed-grid, module-center sampling, and `LayoutInfoBasic` embedded in sync frames. A future **fountain** (喷泉码) protocol is planned.

### Python version constraints

- `src/screen_airdrop/common/**` and `src/screen_airdrop/sender/**` must be Python 3.7 compatible (enforced by `ruff.per-file-target-version`)
- Receiver and dev tooling require Python 3.10+
- Ruff `target-version = "py312"` applies to everything except the above overrides

### Tests

- `tests/unit/` — pure logic tests, no hardware needed
- `tests/integration/` — loopback and lossy frame pipeline tests
- `tests/e2e/` — real captured frame datasets (marker: `real_data`, `regression_data`)
- Fixtures with real frame data live in `tests/fixtures/real_data/`
