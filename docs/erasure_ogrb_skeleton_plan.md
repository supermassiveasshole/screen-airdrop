# Erasure and OGRB Skeleton Plan

Status: sparse-XOR erasure baseline complete; GF(2^8) erasure baseline complete; OGRB scheduling skeleton only  
Scope: information-layer erasure skeleton and OGRB scheduling skeleton  
Non-goal: this document does not authorize immediate implementation of coded transport semantics, solver logic, or wire-format changes

Current implementation note:

1. receiver-side sparse-XOR solver baseline now exists in `receiver/information/`
2. coded information units and equation identity are implemented
3. end-to-end coded-path wiring exists for tests, controlled replay, benchmark use, and sender-side formal coded controls
4. coded emission now applies to uniform-payload short generations as well as full generations; only variable-size generations remain systematic-only
5. default live/replay behavior is still systematic-only
6. the sparse-XOR erasure baseline is now treated as complete
7. the current formal coded baseline is `GF256_SEED_V2`; `GF256_SEED_V1` remains compatibility-only; OGRB policy remains future work

Baseline completion summary:

1. `Sparse XOR / GF(2)` is retained only as a historical baseline reference
2. sender-side coded controls are formal and stable:
   - `emit_coded_units`
   - `coded_redundancy_count`
   - `coded_degree`
3. the current coded family is `GF256_SEED_V2`; `GF256_SEED_V1` is retained only for compatibility and benchmark comparison
4. short generations with uniform payload size now participate directly in `GF256_SEED_V2`; variable-size generations remain systematic-only until a future explicit padding/tail profile exists
5. multi-loss recovery, insufficient-equation behavior, and failure-mode observability are covered in tests
6. dependent-equation observability and benchmark comparability are explicit
7. the formal robustness matrix is degree `2/3/4` by redundancy `1/2/4`
8. OGRB lifecycle/fairness/budget scheduling remains out of scope

## Test Slices

The current erasure work is intentionally split into two pytest slices:

1. `erasure_experiment`
   - coded payload envelope
   - coded builder and scheduling helpers
   - generation-store / solver / information-layer recovery tests
2. `replay`
   - replay-pipeline coverage, including slower end-to-end recovery tests

Recommended commands:

```bash
# fast erasure-focused unit coverage
uv run pytest \
  tests/unit/test_coded_payload_envelope.py \
  tests/unit/test_generation_store.py \
  tests/unit/test_sender_epochs.py \
  tests/unit/test_sender_unit_schedule.py \
  -m "erasure_experiment and not replay"

# replay-heavy erasure coverage
uv run pytest \
  tests/integration/test_receiver_loopback.py \
  -m "replay and erasure_experiment"

# replay coverage without the coded erasure experiments
uv run pytest \
  tests/integration/test_receiver_loopback.py \
  tests/integration/test_receiver_lossy.py \
  -m "replay and not erasure_experiment and not real_data"
```

These markers are for test organization only. They do not change default sender/receiver behavior. Coded erasure is now a formal sender capability, but still opt-in rather than default.

## 1. Purpose

This document defines the minimum architecture needed to add:

1. erasure-oriented information semantics
2. coded transmission units
3. generation-local decoding state
4. OGRB scheduling over systematic and coded units

The purpose is to establish the next major implementation boundary after the current refactor work. It is not another package-migration plan. The package structure is already sealed; this document defines the semantic skeleton that should be added inside that structure.

## 2. Current Baseline

The current codebase already provides the following prerequisites:

1. structural reorganization is complete
2. top-level compatibility modules are retired
3. `information`, `scheduling`, `transport`, `pipeline`, `runtime`, `reporting`, `roi`, and `locator` are stable subdomains
4. the system is in a real-generation, systematic-only phase
5. transport `epoch_id` is still transport metadata, not information-layer `generation_id`

That means the next step is not more structural cleanup. The next step is to add semantic skeletons for erasure coding and OGRB without breaking the existing separation between:

1. information layer
2. scheduling layer
3. visual transport layer

## 3. Layer Boundaries

The following boundaries must remain strict.

### 3.1 Information Layer

The information layer defines:

1. `TransmissionUnit`
2. `SystematicUnit`
3. `CodedUnit`
4. generation identity
5. source identity
6. equation identity
7. receiver-side generation decode state

The information layer does not define:

1. frame timing
2. transport headers
3. visual layout
4. render cadence

### 3.2 Scheduling Layer

The scheduling layer defines:

1. which unit to send next
2. how generations are revisited
3. how systematic and coded units are mixed
4. redundancy policy
5. OGRB policy state

The scheduling layer does not define:

1. what a coded equation means
2. how a frame is rendered
3. how a frame is decoded visually

### 3.3 Transport Layer

The transport layer defines:

1. how one unit is encoded into one visual frame
2. how a valid decoded frame yields exactly one normalized result
3. how invalid frames become erasures

The transport layer does not define:

1. coded-equation semantics
2. scheduling policy
3. generation completion

## 4. Target Skeleton

The intended skeleton is:

```text
common/
  information/
    units.py
    identities.py
    coding.py

  scheduling/
    interfaces.py
    policies.py

sender/
  information/
    generation_builder.py
    unit_builder.py
    coded_builder.py

  scheduling/
    unit_schedule.py
    ogrb_scheduler.py

receiver/
  information/
    assembler.py
    generation_store.py
    unit_acceptor.py
    solver_state.py
    decoder.py
```

Not every file above needs to exist on day one, but these are the stable landing zones for the erasure and OGRB work.

## 5. Information-Layer Skeleton

### 5.1 Units

The information layer should converge on two concrete unit kinds:

1. `SystematicUnit`
2. `CodedUnit`

`SystematicUnit` already exists. The next addition is `CodedUnit`.

Minimum `CodedUnit` fields:

1. `session_id`
2. `generation_id`
3. `generation_size`
4. `equation_id`
5. `payload_size`
6. `payload`
7. either `coding_seed` or explicit coefficient description
8. `degree`

Rules:

1. `SystematicUnit` identity is `(generation_id, source_index)`
2. `CodedUnit` identity is `(generation_id, equation_id)`
3. those identity spaces must remain separate
4. coded equations must never be collapsed into source-symbol identity

### 5.2 Generation State

Receiver-side generation state must evolve from a systematic bucket into a mixed decode state.

Minimum per-generation fields:

1. `generation_id`
2. `generation_size`
3. `systematic_symbols`
4. `received_source_ids`
5. `coded_equations`
6. `received_equation_ids`
7. `decode_complete`
8. `decoded_payload_ready`

The current `GenerationStore` is the correct host for this growth.

### 5.3 Solver State

The system should introduce a dedicated solver-state module rather than folding coded state into `assembler.py`.

Recommended role for `receiver/information/solver_state.py`:

1. hold equation rows
2. track independent vs duplicate equations
3. track rank
4. expose whether the generation is solvable
5. remain independent from restore/materialization logic

This solver state should remain internal to information-layer decoding. Runtime, pipeline, and transport must not understand row reduction details.

### 5.4 Information Decoder

Receiver-side information decoding should be split conceptually into:

1. unit acceptance
2. generation-state update
3. decode/solve attempt
4. materialization into ordered chunk payloads

That implies a future `receiver/information/decoder.py` or equivalent helper with responsibilities like:

1. apply a `TransmissionUnit` to generation state
2. determine whether it is duplicate, useful, or ignorable
3. trigger decode completion when enough independent information exists

## 6. Erasure Skeleton

The channel model should remain strict:

1. valid decoded frame -> exactly one `TransmissionUnit`
2. invalid frame -> erasure

Erasure support in this phase means:

1. the receiver can survive missing systematic units
2. coded units are treated as additional equations, not as replacement semantics
3. generation completion depends on decoded source recovery, not on raw frame count

The erasure skeleton therefore requires:

1. equation identity
2. rank tracking
3. duplicate-equation rejection
4. distinction between "received enough frames" and "recovered the generation"

It does not require transport changes by itself.

## 7. OGRB Skeleton

OGRB should be added as a scheduling skeleton only after information-layer coded semantics exist.

### 7.1 Scheduler Contract

The scheduling layer should expose a stable scheduler interface that accepts:

1. available generations
2. per-generation sender state
3. current systematic/coded production capabilities
4. policy parameters

And yields:

1. the next `TransmissionUnit` to emit
2. optional scheduler-side metadata for observability

Recommended conceptual interface:

1. `UnitScheduler`
2. `ScheduledUnit`
3. `TransmissionSchedule`

The scheduler should not know transport frame format. It operates on units only.

### 7.2 Sender-Side OGRB State

Sender-side OGRB state will need at least:

1. generation backlog
2. current generation frontier
3. revisit candidates
4. redundancy budget
5. coded/systematic mix policy

This belongs under `sender/scheduling/`, not under transport or controller orchestration.

### 7.3 Minimum OGRB Phases

The intended progression is:

1. systematic-only fixed ordering
2. mixed systematic + coded without overlap
3. revisit policy across multiple generations
4. full OGRB policy tuning

That means the first true OGRB implementation should still start simple:

1. non-overlapping generations
2. explicit switch from systematic emission to coded emission
3. no feedback channel
4. no adaptive rate tuning

## 8. Recommended Implementation Order

Implementation should proceed in this order.

### Phase A: Information Types

1. add `CodedUnit`
2. add equation identity types
3. add coefficient metadata model
4. keep transport unchanged

### Phase B: Receiver Decode State

1. extend `GenerationStore`
2. add solver state
3. add receiver information decoder
4. keep sender systematic-only

### Phase C: Sender Coded Production

1. build coded-unit creation path
2. allow sender to emit either systematic or coded units
3. keep scheduler simple and deterministic

### Phase D: Basic Mixed Scheduler

1. introduce a scheduler that can select between systematic and coded units
2. still use non-overlapping generations
3. no adaptive OGRB policy yet

### Phase E: OGRB Policy Work

1. revisit policy
2. overlapping generations if needed
3. budget tuning
4. observability and benchmarks

## 9. Explicit Non-Goals

This skeleton plan does not imply immediate work on:

1. transport wire-format expansion
2. visual header redesign
3. feedback channel design
4. adaptive congestion control
5. GUI tooling
6. benchmark optimization

Those can follow after the skeleton is in place.

## 10. Exit Criteria For Skeleton Readiness

The erasure and OGRB skeleton should be considered ready to implement when all of the following are true:

1. `CodedUnit` and equation identity are defined in `common/information`
2. receiver generation state can store systematic and coded information separately
3. a dedicated solver-state host exists
4. sender has a stable place to produce coded units
5. scheduling contracts can choose units without knowing transport details
6. transport adapters still normalize one frame into one unit-or-erasure result
7. no runtime or pipeline module needs to understand equation algebra

## 11. Practical Rule For Future Work

When adding erasure or OGRB code, each new change should answer this question:

`Is this information semantics, scheduling policy, or visual transport?`

If the answer is unclear, the design is probably crossing boundaries and should be corrected before implementation.
