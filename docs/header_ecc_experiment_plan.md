# Header ECC Experiment Plan

Date: 2026-03-16
Status: Proposed
Scope: `gray4` stage only

## Goal

Compare several **single-frame** header protection schemes and decide whether
any of them improve the current `gray4` failure mode without imposing an
disproportionate decode/runtime cost.

This plan explicitly avoids:

- cross-frame header fusion
- generation/group-level redundancy
- OGRB-style recovery logic

Those belong to later stages.

## Problem Statement

Current evidence shows two distinct failure classes:

1. `chunk 10 / 47 / 77`
   - fail with `E2003: bad v3 magic`
   - primary issue is header/control decode margin

2. `chunk 170`
   - fail with `E2004: payload crc mismatch`
   - primary issue is payload robustness, not header

This plan focuses only on class 1.

## Constraints

Any candidate header ECC scheme must satisfy all of the following:

1. Single-frame only
2. No cross-frame dependence
3. Compatible with current `gray4` stage boundaries
4. Measurable decode cost
5. Revertible if it adds cost without improving bad-frame recovery

## Candidate Schemes

### Baseline A: Current Header Repetition + CRC

Current behavior:

- header bits repeated according to the current in-frame design
- header unpack guarded by header CRC
- decoder uses threshold candidates + limited bit flipping

Purpose:

- baseline for both recovery and cost

### Candidate B: Stronger Header Repetition

Description:

- keep the current binary header structure
- increase repetition only for the header region
- payload encoding unchanged

Notes:

- already tested in a simple form
- did not help enough and disturbed payload start alignment
- should remain in the comparison table only as a negative control

### Candidate C: Header-Specific Short Block Code

Description:

- replace pure repetition with a real short code for header bits
- examples:
  - Hamming-family
  - shortened BCH-style code
  - another lightweight binary block code that can be implemented locally

Desired properties:

- true error correction, not just redundancy
- fixed-size single-frame block
- decoder remains local to the header path

This is the most promising direction if we continue header ECC work.

### Candidate D: Header Erasure-Aware Decode Only

Description:

- keep the existing wire format
- improve decode by treating weak header bits as erasures
- attempt decode using confidence-ranked bit handling before payload decode

Notes:

- this is still a decoder-side experiment, not a wire-format change
- lower implementation risk than a new block code
- useful as a control experiment before adding a new code

## Comparison Dimensions

Every candidate must be compared on both correctness and cost.

### Correctness Metrics

1. Representative bad frames recovered
   - at minimum:
     - `000012.npy`
     - `000049.npy`
     - `000079.npy`

2. Clean roundtrip still passes

3. No regression on already-good neighboring frames

4. No new failure class introduced

### Cost Metrics

1. Additional decode latency per frame
2. Additional worst-case decode latency on bad frames
3. Sender-side payload capacity loss
4. Any measurable throughput regression in live pipeline

## Experiment Matrix

### Phase 1: Decoder-Only Controls

Purpose:

- establish how much margin can be recovered without changing the wire format

Experiments:

1. Current baseline
2. Erasure-aware header decode
3. More aggressive header-only retry using weak-bit sets

Decision rule:

- if decoder-only methods recover the bad header frames cheaply, prefer them
- if not, move to header-specific block code experiments

### Phase 2: Wire-Format Header ECC Candidates

Purpose:

- compare true single-frame header ECC schemes

Experiments:

1. Current repetition baseline
2. Stronger repetition baseline
3. Short block code candidate 1
4. Short block code candidate 2

Decision rule:

- reject any candidate that materially increases cost but does not recover the
  representative bad header frames

### Phase 3: End-to-End Sanity Check

Purpose:

- verify the chosen candidate does not create a net system regression

Required checks:

1. Integration tests
2. Representative captured-replay bad frames
3. Live local screen run
4. Throughput impact summary

## Required Experiments

### Experiment 1: Baseline Capture

Collect:

- current bad-frame results
- current decode latency
- current throughput

Reference inputs:

- captured replay frames already isolated in `/tmp/gray4-captured-replay`

### Experiment 2: Bad-Frame Header Recovery

Run each candidate against:

- `000012.npy`
- `000049.npy`
- `000079.npy`

Record:

- success/failure
- elapsed decode time
- failure code

### Experiment 3: Neighbor Non-Regression

For each bad-frame window, also run:

- previous neighbor
- next neighbor

Reason:

- candidate must not break frames that are currently decodable

### Experiment 4: Throughput / Cost Check

Run:

- local pipeline capture
- representative `gray4` sender settings

Record:

- `cap_fps`
- `dec_fps`
- `copy_ms`
- `dedup_ms`
- decode latency and success rate

## Acceptance Criteria

A header ECC candidate is acceptable only if:

1. It improves at least one representative header-failure frame
2. It does not regress good neighbors
3. It does not materially regress clean roundtrip behavior
4. It does not impose an unacceptable decode-cost increase

If those conditions are not met, revert and do not keep the experiment.

## Reversion Rule

All experiments must be implemented behind a narrow toggle or isolated code
path.

If a candidate:

- fails to improve representative bad frames
- or increases decode cost without enough recovery benefit

then it should be removed or disabled immediately, restoring baseline behavior.

## Recommendation

Proceed in this order:

1. Decoder-only erasure-aware header experiment
2. If still insufficient, prototype a single header-specific short block code
3. Compare against current repetition baseline
4. Keep only what shows measurable recovery gain with controlled cost

Do not:

- introduce cross-frame header recovery here
- mix this work into OGRB/layered control-plane design
- keep "interesting but unhelpful" decode complexity in the main path

## 2026-03-15 Findings

The first ECC experiments are now completed.

### Decoder-only header recovery

Tried on representative bad frames:

- `000012.npy`
- `000049.npy`
- `000079.npy`

Candidates:

- baseline
- aggregate flips
- erasure-aware

Result:

- none of them recovered the representative bad frames
- failures remained `E2003: bad v3 magic`

Conclusion:

- decoder-only search variants are not enough

### Critical-header short-code experiment

Two single-frame profiles were evaluated against real captured bad frames:

1. `critical_v0`
   - 14 bytes / 112 bits
   - fields:
     - `magic`
     - `version`
     - `frame_type`
     - `session_tag`
     - `frame_id`
     - `chunk_id`
     - `payload_len`
     - `crc16`

2. `tiny_v0`
   - 10 bytes / 80 bits
   - fields:
     - `magic`
     - `version`
     - `frame_type`
     - `chunk_id`
     - `payload_len`
     - `crc16`

Code families:

- repetition-1
- repetition-2
- Hamming(7,4)
- SECDED(8,4)

Placement models:

- `front`
- `stride`
- `best_abs` (optimistic oracle using strongest observed cells)

Result:

- none of the code families recovered any representative bad frame
- this remained true even for `tiny_v0`
- this remained true even under `best_abs`

Conclusion:

- the current bad frames are not explained by "header needs a slightly better code"
- within the current single-frame header cell budget, code-family changes alone are not enough
- the next promising direction is physical/header placement redesign, not more repetition experiments
