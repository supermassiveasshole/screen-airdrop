# Screen-Airdrop Throughput Optimization Strategy

**Version**: 1.1
**Date**: 2026-03-15
**Status**: Master Plan

---

## Document Purpose

This is the **master strategy document**, not a task list.

It answers five questions:

1. What are we optimizing?
2. What have we learned so far?
3. What architectural principles guide protocol evolution?
4. What does each phase solve?
5. What's the next priority?

**Related Documents**:
- [ogrb_specification.md](./ogrb_specification.md) - OGRB protocol specification
- [protocol_efficiency_report.md](./protocol_efficiency_report.md) - Single-frame efficiency analysis
- [benchmark_status.md](./benchmark_status.md) - Current benchmark results
- [information_density_kickoff.md](./information_density_kickoff.md) - Phase kickoff tasks

---

## Executive Summary

**Current State**: The system works like "animated QR codes" - each frame is a complete packet, lost frames wait for next epoch, heavy frame-internal ECC.

**Problem**: This approach has a low ceiling. Single-frame overhead (finder, timing, header, repetition ECC) dominates at high redundancy levels (Q/H).

**Goal**: Transform from "per-frame image protocol" to "visual physical layer + lightweight link layer". Make each frame an efficient symbol carrier that upper recovery layers can utilize.

**Key Insight**: Don't make frames "more perfect QR codes". Instead, move recovery responsibility from frame-internal to cross-frame coding.

---

## Current Status

### Completed Phases

**Phase 0: Protocol Interface Decoupling** ✓
- `LayoutInfo`, `ProtocolEncoder`, `ProtocolDecoder` interfaces established
- `basic` protocol working through unified interface

**Phase 1: Compact Protocol** ✓
- Reduced static structure overhead
- Benchmarked across three layers: synthetic CPU, real-frame decode, end-to-end
- Results: ~11% payload increase, ~14-15% throughput improvement over `basic`

### Key Findings

1. **Compact is validated**: Real improvement confirmed in local screen capture
2. **L-level ECC is viable**: `--ecc-level L` achieves ~40 KB/s in current test environment
3. **Capture is the bottleneck**: Not locator (grab: 50-70ms, locate: 20-30ms, decode: 10-15ms)
4. **Gray4 payload is not currently the first failure mode**:
   - On clean replay, `gray4` payload decode is now stable and full file restore succeeds
   - Under controlled blur (`gaussian_blur_5`), the first observed failure is still `bad v3 magic`
   - This means the current bottleneck is **control/header survivability**, not payload FEC strength

### Gray4 Interim Status

`gray4` has now crossed the threshold from "prototype that may or may not work" to "payload modulation path is viable, but control-plane robustness is the limiting factor."

What is already established:
- `gray4` can exceed prior `compact` throughput in clean local screen conditions
- `gray4` replay/debug datasets show `data plane` can decode correctly when capture is ideal
- Additional payload-only demodulation tweaks do not address the dominant blur failure mode
- Low-cost sender-side diversity can matter: in a static display/capture chain,
  changing data-frame masks across epochs has been observed to recover chunks
  that remained permanently missing under deterministic replay of the same
  visual pattern

What is not yet solved:
- Header/control decode still collapses before payload under moderate blur
- Therefore, simply adding stronger payload coding would not solve the real entry problem
- The next architectural step is no longer "more gray4 tuning", but "explicit robust control plane"

**Implication**: Prioritize single-frame information density and decode stability before major locator refactoring.

---

## Architectural Principles

### Two-Layer Separation

Protocol evolution splits into two independent layers:

#### A. Single-Frame Physical Layer (Phase 1-3)

**Responsibilities**:
- Increase per-frame information density
- Reduce static structure overhead
- Improve frame-level detectability
- Ensure header/control plane is easily identifiable

**Directions**: `compact`, `gray4`, `layered`

**Four Sub-Problems**:
1. **Geometric Localization**: Find frame, recover corners, estimate perspective transform
2. **Phase & Sampling**: Estimate sampling phase from timing/pilot, determine module centers
3. **Symbol Decision**: Binary threshold (basic/compact), 4-level slicing (gray4), layered strategies
4. **Frame-Level Validity**: Is header trustworthy? Is payload trustworthy? Accept, discard, or treat as erasure?

**Critical Observation**:
- The control plane is the receiver's entry condition
- If header/control dies first, payload redundancy is irrelevant because the receiver never enters the correct decode state
- Therefore future physical-layer work MUST treat control/header survivability as a first-class design axis, not as a side-effect of payload modulation
- Separately, data-plane retries SHOULD NOT assume that repeating the exact
  same rendered pattern is meaningful recovery; in static visual channels,
  sender-side diversity may be required to turn retries into genuinely new
  recovery opportunities
- This applies not only across epochs but also within any future sliding-window
  or overlap-based redundancy scheme: repeated transmission of the same logical
  chunk/symbol SHOULD be allowed to vary its visual realization (for example
  mask, whitening, or placement seed), otherwise redundancy remains too
  correlated under static display/capture conditions

#### B. Cross-Frame Recovery Layer (Phase 4-5)

**Responsibilities**:
- Treat missing frames as erasures
- Generation-based recovery
- Rateless/fountain broadcast
- Mid-session join and continuous recovery

**Directions**: `erasure`, `fountain` (specifically OGRB)

**Key Constraint**: MUST NOT depend on specific frame arrival or visible epoch boundaries.

### Two Parallel Paths

These paths are NOT mutually exclusive:

**Path 1: Modulation** - Increase bits/module
- `compact` → `gray4` → `layered`
- Question: Can we pack more information per frame without losing decode stability?

**Path 2: Frame-Internal Protection** - Reduce redundancy tax
- Re-evaluate L/M/Q/H levels
- Weaken heavy repetition ECC
- Move recovery responsibility to outer layer (erasure/fountain)
- Question: Should bad frames be quickly marked as erasures instead of heavily protected?

---

## Why Current Protocol Loses to Large QR Codes

Detailed analysis in [protocol_efficiency_report.md](./protocol_efficiency_report.md).

**Summary**:

1. Current protocol single-frame utilization is low - not because implementation is "unfilled"
2. Main losses:
   - Repetition ECC (especially at Q/H levels)
   - Static structure overhead
   - Header
   - Sender's 0.9 safe cap
3. At **L level**, current protocol has structural competitiveness
4. At **M/Q/H levels**, gap vs large QR remains significant

**Conclusion**: If single-frame optimization continues, priority should be:
1. Increase modulation efficiency (gray4/layered)
2. Redesign frame-internal ECC strategy
3. Stop treating heavy repetition as long-term default

---

## L-Level ECC is a First-Class Track

**Critical Judgment**:

> L-level SHOULD be treated as a first-class benchmark track for local screen-capture channels, because heavy frame-internal ECC may no longer be the right default assumption.

**Rationale**:
1. Local `screen + manual ROI` is much cleaner than camera scenarios
2. Theoretical analysis shows L is the only level where current protocol approaches QR single-frame density
3. If L is stable in real screen capture, heavy frame-internal repetition is no longer justified

**This does NOT mean**:
- Abandon frame validation entirely

**This DOES mean**:
- Keep lightweight frame checks (header CRC, payload CRC)
- Stop defaulting to heavy redundancy repetition as primary recovery
- Gradually move recovery responsibility to `erasure/fountain`

---

## Phase Roadmap

### Phase 0: Protocol Interface Decoupling ✓

**Status**: Complete

**Goal**: Enable protocol coexistence through unified interface

**Deliverables**:
- `LayoutInfo` dataclass
- `ProtocolEncoder` / `ProtocolDecoder` interfaces
- `basic` adapter implementation

### Phase 1: Compact Protocol ✓

**Status**: Complete

**Goal**: Compress static structure overhead, validate tighter layout brings real gains

**Results**:
- Validated: Real improvement in local screen benchmark
- ~11% payload increase, ~14-15% throughput improvement

### Phase 2: Gray4 Protocol

**Status**: In progress / partially validated

**Goal**: Evaluate if 4-level grayscale modulation brings real throughput gains in screen capture

**Questions to Answer**:
1. Can 4-level grayscale improve throughput in local screen capture?
2. Does increased error rate offset theoretical capacity gain?
3. Should gray4 be layered on `compact` or prototyped independently?
4. Is L-level still the right benchmark working point for gray4?

**Constraints**:
- Keep finder/timing/locator mostly unchanged
- Prioritize changes to: payload modulation, symbol slicing, calibration/pilot

**Updated Judgment From Current Work**:
- `gray4` has answered the payload-density question enough to continue
- The remaining critical blocker is not "can 4-level payload work", but "can control/header remain decodable before payload under blur"
- Therefore `gray4` SHOULD NOT absorb increasingly complex control-plane work that properly belongs to `layered`

**Core Algorithm Focus**:

1. **Data Region 4-Level Modulation**
   - Each payload module carries 2 bits
   - Finder/timing/control plane stays binary initially

2. **Local Grayscale Calibration**
   - Cannot rely on fixed threshold
   - Use pilot/reference cells to estimate: black level, white level, two intermediate gray centers

3. **Decoder Slicing**
   - Input: module local brightness statistics
   - Output: 0/1/2/3 with confidence score
   - Confidence enables outer layer or layered design usage

4. **Gray4 Benchmark Must Track**:
   - Frame success rate
   - Bad frame rate
   - Locator fail rate
   - Goodput
   - Whether first failure is control-plane or data-plane

**Recommended Implementation Order**:
1. Keep finder/timing/header binary
2. Only payload region enters 4-level modulation
3. Start with global slicing
4. Add pilot-based local slicing
5. Add limited header/control decode hardening only insofar as it informs later `layered` work
6. Finally decide if worth combining with different L/Q ECC working points

**Specification Boundaries** (MUST):
1. Finder/timing/header regions stay binary
2. Only payload region enters 4-level modulation
3. Decoder output includes both: decision value + confidence/quality metric
4. Benchmark results MUST report at minimum: frame success rate, bad frame rate, locator fail rate, goodput
5. Gray4 evaluation MUST explicitly record whether the first failure mode is:
   - control/header decode failure
   - payload decode failure
   - locator failure

**Specification Boundaries** (SHOULD NOT):
- Do NOT simultaneously introduce: header/data layered rewrite, new tracker, new capture backend
- Otherwise cannot determine gain source
- Do NOT try to solve long-term control-plane robustness purely inside `gray4` if the result effectively becomes a hidden `layered` protocol

**Acceptance Criteria**:
1. Synthetic roundtrip passes
2. Replay benchmark at least not worse than `compact`
3. Local-screen benchmark shows clear gain
4. Both L and Q preserved in parallel benchmark results

### Phase 3: Layered Protocol

**Status**: Not started

**Goal**: Validate whether header/data layered design can improve both:
- effective single-frame payload capacity
- robustness of frame entry / control recovery

**Expected Value**:
- Header maintains higher robustness than the main data area
- Payload area gains effective capacity by not sharing the same protection budget as control information
- Overall single-frame payload efficiency increases relative to non-layered layouts
- Prepares for outer code

**Key Understanding**:

`layered` is NOT simply "split frame into upper/lower halves". It's about separating **control plane** vs **data plane** responsibilities so that the protocol is both:
- more robust at frame entry and control recovery
- more payload-efficient at the same overall screen budget

**Control Plane**:
- frame_id, session_id, generation_id, symbol type, mode/layout info
- Requirements: high robustness, easy decision, allow lower capacity

**Refined Interpretation**:
- Control plane is not "just a small header"
- It is the receiver's **strong synchronization and semantic lock layer**
- It MAY consume disproportionate area, repetition, or time redundancy if that is what is required to stay alive under blur/compression
- Its job is to let the receiver answer: "what kind of frame is this and how should I treat it?" before any aggressive payload demodulation happens

**Historical Intent To Preserve**:
- `gray4` and `layered` are both part of the single-frame capacity track
- `gray4` asks whether denser modulation is viable
- `layered` asks whether header/data stratification can raise effective capacity and robustness together
- `layered` MUST NOT be reinterpreted as a robustness-only side branch

**Data Plane**:
- Actual payload symbols
- Requirements: higher density, allow higher error rate, on failure prefer handing to outer layer as erasure

**Algorithm Key**: Not "add more structure", but:
- Header region can be conservative
- Data region can be aggressive
- Don't share same redundancy budget

**Specification Boundaries** (MUST):

`layered` implementation MUST explicitly output two independent design decisions:

1. Control plane: modulation method, redundancy strategy, decision criteria
2. Data plane: modulation method, redundancy strategy, failure handling

**Goal**: Not "increase overall complexity", but:
- Make control plane more stable
- Make data plane more aggressive
- Create clearer interface for outer layer erasure recovery

**Minimum Design Direction For `layered`**:

`layered` SHOULD be treated as the first phase where control plane is designed explicitly as a robust channel, potentially including:
- coarse header vs inner header split
- larger or lower-frequency control symbols than payload symbols
- binary-only control symbols even if payload uses gray4 or richer modulation
- spatial repetition (for example multiple edges/rings) and/or temporal repetition across a short frame window
- partial header recovery sufficient to classify frame type/group even when full inner metadata is unavailable

**Normative Consequence**:
- Future `layered` work MUST NOT model control fields as ordinary payload bytes with only small local protection
- Future `layered` work SHOULD assume that preserving minimal frame identity is more important than maximizing control-plane density

### Phase 4: Erasure Coding

**Status**: Not started

**Goal**: Generation-based erasure recovery - let bad frames naturally become erasures instead of waiting for sequential wraparound

### Phase 5: Fountain Coding (OGRB)

**Status**: Not started

**Goal**: Rateless/sliding-window broadcast, support mid-session join and continuous recovery

**See**: [ogrb_specification.md](./ogrb_specification.md) for complete specification

---

## OGRB Design Summary

Full specification in [ogrb_specification.md](./ogrb_specification.md). Key points:

**What OGRB Is**:
- **O**verlapping **G**eneration **R**ateless **B**roadcast
- Short-cycle rateless broadcast with limited generation overlap
- NOT whole-file fountain (too complex, too slow)

**Why Not Whole-File Fountain**:
1. Decode complexity too high
2. Time-to-first-recovery too long
3. Revisit cycle uncontrollable
4. Debugging complexity excessive

**Three-Layer Structure** (MUST be kept separate):

1. **Physical Frame Layer**: Carry one symbol per frame, header identifiable, payload trustworthy → deliver, bad frame → erasure
2. **Generation Coding Layer**: Split data into small generations, each independently recoverable
3. **Broadcast Scheduling Layer**: Decide which generation to send, systematic vs coded, airtime allocation between old/new generations

**Three Core Trade-offs**:

1. **Forward Progress**: How fast new data enters transmission
   - Controlled by: overlap, max_active_generations, old_new_ratio

2. **Revisit Pressure**: How fast old generations get additional recovery opportunities
   - Controlled by: overlap, old_new_ratio, max_active_generations

3. **Recovery Robustness**: Probability generation completes under packet loss
   - Controlled by: generation_size, coded_redundancy, systematic_prefix, decode_margin

**Key Design Decisions**:

1. **Overlap is expensive**: Don't default to high overlap in high-loss scenarios
   - Priority: reduce generation_size → increase redundancy → increase old_new_ratio → only then increase overlap

2. **max_active_generations = 2 is default**: Not 1 (too aggressive), not 3 (fragments airtime)

3. **No sender-side adaptation in v1**: Static profiles with offline benchmarking

**Three Standard Profiles**:

| Profile | Scenario | Generation Size | Overlap | Redundancy | Active Gens |
|---------|----------|----------------|---------|------------|-------------|
| Robust | Remote server, high loss | 12-16 | 0.25 | 1.4-1.6 | 2 |
| Balanced | Local macOS, moderate loss | 20-24 | 0.125-0.25 | 1.15-1.25 | 2 |
| Throughput | Ideal, low loss | 28-32 | 0 | 1.05-1.10 | 1 |

**Default**: Balanced profile (~11 KB generation, ~9.6 KB step size)

---

## Current Priority

If asked "what should we do now?", the answer is:

1. **Finish Phase 2 only to the extent needed to validate gray4 payload viability**
2. **Keep L-level as formal benchmark track**
3. **Stop treating heavy frame-internal repetition as default assumption**
4. **Advance next into explicit control/data separation (`layered`)**
5. **Only after control-plane survivability is clear, advance to erasure/fountain**

In other words, the most reasonable action sequence is:
- Continue improving single-frame physical layer
- Identify whether failures are control-plane or data-plane first
- Move control-plane robustness into an explicit layered design
- Simultaneously loosen single-frame heavy ECC assumption
- Finally migrate primary recovery capability to cross-frame layer

---

## What This Document Does NOT Cover

This document does NOT answer:
- Specific weekly task scheduling
- How to run specific scripts
- Detailed benchmark numbers
- Single-frame efficiency formula derivations

For those, see:
- [information_density_kickoff.md](./information_density_kickoff.md)
- [benchmark_status.md](./benchmark_status.md)
- [frame_decode_success_status.md](./frame_decode_success_status.md)
- [protocol_efficiency_report.md](./protocol_efficiency_report.md)

---

## Directions NOT Currently Committed

This branch does NOT currently commit to:
- `pilot-grid`
- Auto-tracking state machine refactoring
- Capture backend rewrite

These directions are not "never do", but not current mainline path.

**Rationale**: Current bottleneck is capture (50-70ms grab), not locator (20-30ms). Prioritize single-frame information density and decode stability first.

---

## Normative Language

From this point forward, this document serves as **specification** for protocol evolution.

To reduce implementation ambiguity:
- **MUST**: Implementation must satisfy
- **SHOULD**: Default recommendation; if not satisfied, must provide clear rationale
- **MAY**: Optional implementation

If this document conflicts with phase-specific discussion records, this document's current version takes precedence.

---

## Interface and Responsibility Boundaries (Normative)

To avoid future implementations re-coupling layers, the following boundaries are normative:

### Single-Frame Physical Layer MUST

- Accept one frame visual carrier
- Output:
  - Is header trustworthy?
  - Is payload trustworthy?
  - If trustworthy, output payload symbols
  - If not trustworthy, output erasure

### Single-Frame Physical Layer MUST NOT

- Perform cross-generation recovery
- Handle broadcast scheduling
- Make global judgments about file completion

### Cross-Frame Recovery Layer MUST

- Accept from single-frame layer: systematic symbols, coded symbols, erasures
- Independently maintain generation state
- Decide when generation can be recovered, when complete

### Cross-Frame Recovery Layer MUST NOT

- Depend on any specific frame must arrive
- Depend on epoch boundaries being visible

### Header/Payload Separation MUST Be Clear

- Header handles control plane information
- Payload handles data plane information
- Future `layered` design MUST maintain this responsibility separation, not mix back into single redundancy budget
- Header/control plane MUST be allowed to use a different survivability strategy than payload, including:
  - lower modulation order
  - larger symbols
  - stronger spatial repetition
  - stronger temporal repetition
  - partial-decode semantics

### Control Plane MUST Be Treated As Entry State

- The receiver MUST be able to establish minimal frame identity before aggressive payload recovery is attempted
- Outer recovery layers such as OGRB/fountain MUST assume a stable control/group identity layer exists
- If a design causes control-plane failure to dominate before payload failure, that design SHOULD be considered control-limited, not payload-limited

### OGRB Dependency Boundary MUST Stay Explicit

- OGRB/fountain can recover missing or erased payload symbols after frame identity is established
- OGRB/fountain MUST NOT be treated as a substitute for robust control/header decode
- Group-stable control metadata is a prerequisite for generation-level recovery, not a consequence of it

---

**End of Strategy Document**
