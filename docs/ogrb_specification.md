# OGRB Protocol Specification

Version: 3.1-draft
Status: Design draft with real-generation systematic baseline active in code; sparse-XOR erasure baseline complete; GF(2^8) erasure baseline complete; OGRB scheduler policy remains future work
Target system: Screen-Airdrop visual transmission pipeline

## 1. Introduction

This document specifies OGRB for Screen-Airdrop as a **sender-side scheduling protocol** over explicitly defined information-layer transmission units.

OGRB is not a visual renderer. OGRB is not a frame format. OGRB is not a decoder algorithm. OGRB is the policy and state machine that determines **which semantic unit is transmitted next**, under a strict erasure-oriented channel model and a separate visual transport layer.

This rewrite preserves the semantic rigor of the current draft and replaces the remaining scheduler skeleton with implementation-grade protocol rules.

Normative goals:

1. preserve strict separation between information semantics, scheduling, and visual transport
2. preserve strict distinction between `SYSTEMATIC` units and `CODED` units
3. define a sender lifecycle that is implementable without feedback
4. define replay, redundancy, fairness, and termination semantics without ambiguity
5. support overlapping-generation scheduling without weakening identity rules

Current implementation status:

1. the codebase already uses real semantic `generation_id`
2. sender payload chunks are partitioned into real generations before transport encoding
3. receiver information-layer state already distinguishes systematic symbols from coded equations
4. receiver sparse-XOR erasure recovery exists as the current completed baseline
5. default sender/receiver behavior remains systematic-only unless coded emission is explicitly enabled
6. sender-side coded emission is a formal opt-in capability
7. the current coded baseline is the `GF256_SEED_V2` coding family; `GF256_SEED_V1` remains compatibility-only
8. short generations with uniform symbol size already participate in the current GF(2^8) erasure baseline using their actual `generation_size`
9. OGRB lifecycle/fairness/budget scheduling is not yet implemented

## 2. Normative Language

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are to be interpreted as described in RFC 2119.

## 3. System Overview

The system is defined as three strictly separated layers.

### 3.1 Information Layer

The information layer defines **what** is transmitted.

Its output is a stream of `TransmissionUnit` objects:

1. `SystematicUnit`
2. `CodedUnit`

This layer owns:

1. generation membership
2. source-symbol identity
3. coded-equation identity
4. receiver decode state
5. recovery semantics

This layer does **not** define frame timing, rendering, modulation, or airtime allocation.

### 3.2 Scheduling Layer

The scheduling layer defines **when** each `TransmissionUnit` is transmitted.

This is the OGRB layer. It owns:

1. generation lifecycle
2. active-generation admission and eviction
3. old/new airtime allocation
4. systematic-prefix scheduling
5. fresh coded injection
6. duplicate replay policy
7. overlap-aware generation revisit policy

The scheduling layer MUST operate on semantic units only. It MUST NOT redefine unit semantics.

### 3.3 Visual Transport Layer

The visual transport layer defines **how** one semantic unit is carried over the visual channel.

It owns:

1. frame layout
2. modulation
3. header/control carriage
4. payload carriage
5. integrity checks
6. valid-frame vs erasure classification

It does **not** own:

1. coded-equation meaning
2. generation completion
3. sender lifecycle
4. replay policy

### 3.4 Layer Relation

The normative relation is:

1. information layer defines semantic units
2. scheduling layer chooses unit transmission opportunities
3. visual transport layer carries those opportunities as frames

Any implementation that silently merges these responsibilities is non-compliant.

## 4. Channel Model and Erasure Discipline

Screen-Airdrop operates over a visual channel, not a reliable packet channel.

Typical path:

```text
sender renderer -> compositor -> remote desktop / compression
-> capture -> visual decode
```

The channel may exhibit:

1. tearing
2. frame drop
3. asynchronous capture
4. decode failure
5. pattern-dependent realization failure

### 4.1 Fail-Closed Rule

A captured frame MUST produce exactly one of the following outcomes:

1. one valid semantic payload result
2. erasure

No third outcome is allowed.

Consequences:

1. invalid headers MUST fail closed
2. invalid payloads MUST fail closed
3. invalid frames MUST NOT partially update semantic state
4. invalid frames MUST NOT enter deduplication
5. invalid frames MUST NOT create generation state

### 4.2 Transport Outcome

For OGRB data flow:

1. valid data frame -> exactly one `TransmissionUnit`
2. invalid data frame -> erasure

Control frames remain transport/control-plane concerns and are outside OGRB semantic scheduling.

## 5. Information Layer

This section defines the semantic transmission objects.

### 5.1 Terminology

The following terms MUST be used consistently:

1. `source symbol`
   - one fixed-size source-data unit inside one generation
2. `coded equation`
   - one linear equation over source symbols of one generation
3. `TransmissionUnit`
   - one semantic object carried by transport
4. `frame`
   - one visual transport container
5. `realization`
   - one visual representation of one semantic unit

`unit`, `symbol`, `equation`, and `frame` MUST NOT be used interchangeably.

### 5.2 Generation Model

Source data is partitioned into generations.

Each generation has:

1. `generation_id`
2. `generation_size = K`
3. ordered source-symbol indices `0 .. K-1`

Generation completion means:

1. all source symbols of the generation are known
2. the generation can be materialized in source-index order

Within a generation, symbol size is fixed unless a profile-specific exception is explicitly defined.

For any `TransmissionUnit` in a fixed-size generation:

```text
payload_size MUST equal symbol_size
```

### 5.3 TransmissionUnit

```text
TransmissionUnit =
    SystematicUnit
  | CodedUnit
```

#### 5.3.1 SystematicUnit

Fields:

1. `unit_type = SYSTEMATIC`
2. `generation_id`
3. `generation_size`
4. `source_index`
5. `payload`

Semantic identity:

```text
(generation_id, source_index)
```

#### 5.3.2 CodedUnit

Fields:

1. `unit_type = CODED`
2. `generation_id`
3. `generation_size`
4. `equation_id`
5. `coding_seed` or explicit coefficient description
6. `degree`
7. `payload`

Semantic identity:

```text
(generation_id, equation_id)
```

### 5.4 Identity Model

The protocol recognizes three identity layers.

#### 5.4.1 Semantic Unit Identity

For `SYSTEMATIC`:

```text
(generation_id, source_index)
```

For `CODED`:

```text
(generation_id, equation_id)
```

These identity spaces MUST remain separate.

#### 5.4.2 Realization Identity

If realization diversity is used:

```text
realization_identity = (semantic_unit_identity, realization_index)
```

Realization identity refines semantic identity. It MUST NOT replace semantic identity.

#### 5.4.3 Transport Frame Identity

Transport frame identity, for example `transport_frame_id`, MAY be used for:

1. ordering
2. replay logs
3. transport statistics

It MUST NOT be used for:

1. semantic deduplication
2. generation completion
3. equation identity
4. sender replay accounting

### 5.5 Equation Identity Rule

For a `CodedUnit`, `equation_id` MUST uniquely identify equation content within one generation.

Therefore:

1. two coded transmissions of the same equation MUST preserve the same `equation_id`
2. two different equations within the same generation MUST use different `equation_id`

If an implementation derives equation content from metadata, it MUST ensure deterministic equivalence between:

1. the `equation_id`
2. the equation definition reconstructed from `coding_seed`, coefficient scheme version, and degree

Receiver deduplication MUST use `(generation_id, equation_id)` as the semantic key.

### 5.6 Coded vs Systematic Semantics

`SYSTEMATIC` units are direct values of variables.

`CODED` units are constraints over variables.

In algebraic form:

1. systematic unit:

```text
x_i = payload
```

2. coded unit:

```text
a_0*x_0 + a_1*x_1 + ... + a_(K-1)*x_(K-1) = payload
```

The essential rule is:

**a coded equation is not a source symbol**

### 5.7 Receiver State Model

For each generation, the receiver MUST maintain explicit state with at least:

1. `systematic_symbols: Dict[source_index, payload]`
2. `coded_equations: Dict[equation_id, Equation]`
3. `received_source_ids`
4. `received_equation_ids`
5. `generation_size`
6. `decode_complete`

The following model is forbidden as the primary semantic state:

```python
known_symbols: Set[int]
```

That model collapses systematic and coded identities and is non-compliant.

### 5.8 Receiver Acceptance Logic

Receiver semantic acceptance MUST be equivalent to:

```python
def accept_unit(unit):
    gen = state.get_or_create_generation(unit.generation_id, unit.generation_size)

    if unit.unit_type == SYSTEMATIC:
        sid = (unit.generation_id, unit.source_index)
        if sid in gen.received_source_ids:
            return DUPLICATE
        gen.received_source_ids.add(sid)
        gen.systematic_symbols[unit.source_index] = unit.payload
        return ACCEPTED

    if unit.unit_type == CODED:
        eid = (unit.generation_id, unit.equation_id)
        if eid in gen.received_equation_ids:
            return DUPLICATE
        gen.received_equation_ids.add(eid)
        gen.coded_equations[unit.equation_id] = build_equation(unit)
        return ACCEPTED
```

## 6. Generation Lifecycle

This section defines the **sender-side scheduling lifecycle** of a generation.

Receiver-side decode completion is a separate information-layer state and MUST NOT be conflated with sender scheduling state.

### 6.1 Generation Creation

A generation is `CREATED` when all of the following are true:

1. `generation_id` is assigned
2. generation membership is fixed
3. `generation_size = K` is fixed
4. all semantic identities for the configured systematic prefix are determinable

In the baseline profile, coded scheduling applies only to fixed-size generations.

A variable-size tail generation MUST either:

1. remain systematic-only
2. or be governed by an explicit profile-specific tail-generation rule

### 6.2 Sender Lifecycle States

A generation MUST be in exactly one of:

1. `CREATED`
2. `ACTIVE_SYSTEMATIC`
3. `ACTIVE_CODED`
4. `DRAINING`
5. `COMPLETED`
6. `EXPIRED`
7. `EVICTED`

`COMPLETED`, `EXPIRED`, and `EVICTED` are terminal.

### 6.3 State Semantics

#### CREATED

Rules:

1. MUST NOT emit any unit
2. MUST NOT count in the old-generation pool
3. MAY be held in an admission queue

Entry condition:

1. generation membership becomes fixed

Exit condition:

1. admission to the active generation set

#### ACTIVE_SYSTEMATIC

This state means the generation still owes at least one first transmission of at least one configured systematic-prefix unit.

Rules:

1. MUST be in the active generation set
2. MUST be counted in the new-generation pool
3. MAY emit only systematic units as first transmissions
4. MUST NOT emit a fresh coded equation before all configured systematic-prefix units have been transmitted at least once
5. duplicate systematic retransmissions MAY be used only if a realization policy explicitly requires them; this is not the baseline default

Entry condition:

1. admission of a `CREATED` generation

Exit condition:

1. all configured systematic-prefix units emitted at least once -> `ACTIVE_CODED`
2. deterministic terminal transition -> `EVICTED` or `EXPIRED`
3. feedback-capable variants MAY transition to `COMPLETED`

#### ACTIVE_CODED

This state means the generation has satisfied its systematic-prefix obligation and still has fresh coded budget remaining.

Rules:

1. MUST remain in the active generation set
2. MUST be counted in the old-generation pool
3. MAY emit:
   - fresh coded equations
   - duplicate retransmissions of previously emitted systematic units
   - duplicate retransmissions of previously emitted coded equations
4. fresh coded equation emission SHOULD be preferred over duplicate replay
5. every fresh coded equation MUST use a new `equation_id`

Entry condition:

1. all configured systematic-prefix units have been emitted at least once

Exit condition:

1. fresh coded budget exhausted -> `DRAINING`
2. terminal transition -> `COMPLETED`, `EXPIRED`, or `EVICTED`

#### DRAINING

This state means the generation has no fresh coded budget remaining but is still temporarily eligible for bounded replay.

Rules:

1. MUST remain in the active generation set only while drain budget remains
2. MUST be counted in the old-generation pool
3. MUST NOT emit a new coded equation
4. MAY emit only duplicate retransmissions of previously emitted semantic units
5. duplicate coded replay MUST preserve `equation_id`
6. duplicate systematic replay MUST preserve `(generation_id, source_index)`

Entry condition:

1. fresh coded budget exhausted and drain budget is non-zero

Exit condition:

1. drain budget exhausted -> `EXPIRED`
2. explicit eviction -> `EVICTED`
3. feedback-capable completion -> `COMPLETED`

#### COMPLETED

`COMPLETED` is a terminal sender state.

Rules:

1. MUST NOT emit any additional unit
2. MUST NOT remain in the active generation set
3. MUST NOT count in either pool

Entry condition:

1. explicit positive completion signal from a feedback-capable profile

Baseline rule:

1. a no-feedback baseline sender MUST NOT enter `COMPLETED`

#### EXPIRED

`EXPIRED` is a terminal sender state indicating that the generation aged out or exhausted all configured replay opportunity without completion knowledge.

Rules:

1. MUST NOT emit any additional unit
2. MUST be removed from the active generation set

Entry condition:

1. drain budget exhausted
2. or generation lifetime limit reached

#### EVICTED

`EVICTED` is a terminal sender state indicating forced removal due to active-set pressure or explicit policy.

Rules:

1. MUST NOT emit any additional unit
2. MUST be removed from the active generation set
3. MUST be recorded in sender metrics

Entry condition:

1. deterministic eviction policy selects the generation

### 6.4 Lifecycle Transition Requirements

A compliant baseline sender MUST implement:

```text
CREATED -> ACTIVE_SYSTEMATIC -> ACTIVE_CODED -> DRAINING -> EXPIRED
```

It MAY additionally support:

1. `ACTIVE_* -> EVICTED`
2. `DRAINING -> EVICTED`
3. feedback-gated `ACTIVE_* -> COMPLETED`
4. feedback-gated `DRAINING -> COMPLETED`

A baseline no-feedback sender MUST NOT skip directly from `ACTIVE_SYSTEMATIC` to `DRAINING` unless the configured systematic prefix is empty.

## 7. Replay and Redundancy Semantics

OGRB replay is not "send the same frame again".

OGRB replay is the allocation of additional transmission opportunities to a generation that remains sender-side eligible.

### 7.1 Three Distinct Replay Behaviors

A compliant sender MUST distinguish:

1. identical systematic replay
2. identical coded replay
3. fresh coded injection

These behaviors are not semantically equivalent.

### 7.2 Identical Systematic Replay

An identical systematic replay retransmits the same semantic unit:

```text
(generation_id, source_index)
```

Rules:

1. MUST preserve the same semantic identity
2. MAY use a different `realization_id`
3. provides no new semantic identity
4. MAY provide additional visual diversity
5. SHOULD NOT be the primary replay mechanism once a generation enters `ACTIVE_CODED`

### 7.3 Identical Coded Replay

An identical coded replay retransmits the same coded equation:

```text
(generation_id, equation_id)
```

Rules:

1. MUST preserve the same `equation_id`
2. MAY use a different `realization_id`
3. provides no new semantic identity
4. MUST be treated by the receiver as duplicate semantic information
5. MAY still be useful as a visual-diversity retry

### 7.4 Fresh Coded Injection

A fresh coded injection transmits a coded equation with a new coded identity.

Rules:

1. MUST use a new `(generation_id, equation_id)`
2. MUST correspond to a new deterministic equation definition
3. is the normative replay and redundancy mechanism in `ACTIVE_CODED`
4. counts against fresh coded budget
5. MAY still be linearly dependent at the decoder

### 7.5 Semantic Novelty vs Algebraic Innovation

This specification distinguishes:

1. **semantic novelty**
   - the receiver has not previously accepted this semantic unit identity
2. **algebraic innovation**
   - the received coded equation increases rank or enables recovery

A fresh coded equation MUST be semantically novel. It MAY or MAY NOT be algebraically innovative.

A duplicate coded replay is neither semantically novel nor algebraically innovative.

### 7.6 Bounded Rateless Baseline

The baseline OGRB profile is **bounded rateless-style**, not pure infinite rateless.

This means:

1. the sender MAY generate fresh coded equations on demand from a rateless-like equation family
2. the baseline sender MUST bound fresh coded emission per generation by `B_code_new`
3. the baseline sender MUST bound duplicate replay by `B_drain_dup`
4. once these budgets are exhausted, the generation MUST leave fresh replay and eventually terminate

Therefore:

1. the coded family is rateless-like
2. the baseline scheduling profile is finite-budget

### 7.7 Replay Termination

Replay for a generation MUST terminate when the generation enters:

1. `COMPLETED`
2. `EXPIRED`
3. `EVICTED`

Fresh coded injection MUST terminate when the generation leaves `ACTIVE_CODED`.

Duplicate replay MUST terminate when the generation leaves `DRAINING`.

### 7.8 Replay Preference Order

Absent profile-specific override, a compliant sender SHOULD prefer:

1. configured systematic-prefix first transmissions
2. fresh coded equations
3. duplicate coded replay for visual diversity
4. duplicate systematic replay

## 8. Active Generation Set and Fairness

### 8.1 Active Generation Set

The sender MUST maintain an active generation set with configured integer limit:

```text
G_active_max >= 1
```

Generations in:

1. `ACTIVE_SYSTEMATIC`
2. `ACTIVE_CODED`
3. `DRAINING`

MUST count toward this limit.

Generations in:

1. `CREATED`
2. `COMPLETED`
3. `EXPIRED`
4. `EVICTED`

MUST NOT count toward this limit.

### 8.2 New and Old Pools

The active generation set is partitioned into:

1. `new pool`
   - generations in `ACTIVE_SYSTEMATIC`
2. `old pool`
   - generations in `ACTIVE_CODED`
   - generations in `DRAINING`

This pool split is the normative meaning of old/new airtime ratio in the baseline protocol.

### 8.3 Pool Weighting

The baseline scheduler MUST use integer pool weights:

1. `W_new >= 1`
2. `W_old >= 1`

Configured old/new ratio is:

```text
old_new_ratio = W_old : W_new
```

Floating-point management inputs MAY be accepted externally, but the scheduler MUST convert them to deterministic integer weights before scheduling begins.

### 8.4 Pool Selection Rule

A compliant baseline sender MUST implement weighted fair pool selection.

The normative baseline algorithm is weighted deficit round-robin across the two pools:

1. if new pool is non-empty, add `W_new` to `deficit_new`
2. if old pool is non-empty, add `W_old` to `deficit_old`
3. select the eligible pool with larger deficit
4. on ties, select the old pool
5. after selection, subtract `1` from the selected pool deficit

Equivalent algorithms MAY be used only if they preserve the same fairness and starvation guarantees.

### 8.5 Generation Selection Within a Pool

Within a selected pool, the baseline sender MUST use deterministic round-robin over eligible generations.

Rules:

1. an eligible generation MUST NOT be skipped indefinitely
2. if a pool contains `n` eligible generations, no eligible generation MAY be bypassed for more than `n - 1` consecutive selections of that same pool
3. pool-local order MUST remain stable unless explicit priority override is configured

### 8.6 Starvation Prohibition

A compliant sender MUST prevent permanent starvation.

Specifically:

1. every generation that remains eligible in a non-empty selected pool MUST receive transmission opportunities in finite time
2. no scheduler MAY repeatedly select one eligible generation forever while another eligible generation remains in the same pool
3. pool weighting MAY delay service, but MUST NOT eliminate service to a non-empty pool

### 8.7 Admission Rule

A `CREATED` generation MAY be admitted only if:

1. the active generation set has free capacity
2. or deterministic eviction frees capacity first

Admission MUST transition directly to `ACTIVE_SYSTEMATIC`.

### 8.8 Eviction Rule

If capacity must be freed, the baseline eviction priority MUST be:

1. oldest `DRAINING`
2. oldest `ACTIVE_CODED` with no fresh coded budget remaining
3. oldest `ACTIVE_CODED`
4. `ACTIVE_SYSTEMATIC` only if no other evictable generation exists

A sender MUST NOT evict an `ACTIVE_SYSTEMATIC` generation with unfulfilled systematic-prefix obligation while any `DRAINING` generation remains evictable.

### 8.9 Overlap and Fairness

If overlapping generations are enabled, overlap affects only:

1. generation membership
2. active-set concurrency

Overlap MUST NOT change:

1. semantic identity rules
2. pool definitions
3. duplicate semantics

An older overlapping generation does not re-enter `ACTIVE_SYSTEMATIC`. It remains in its current lifecycle state until terminal transition.

## 9. Integerized Generation Geometry

This section defines the baseline rule for generation start, step, and overlap.

### 9.1 Integer Parameters

The following parameters MUST be integers at runtime:

1. `generation_size = K`
2. `generation_start`
3. `step_size`
4. `effective_overlap`

A configuration surface MAY accept a fractional target overlap ratio, but the sender MUST integerize it before generation construction.

### 9.2 Target Overlap Ratio

Let:

1. `alpha_target` be configured overlap ratio in `[0, 1)`
2. `K` be generation size

Define:

```text
raw_step = K * (1 - alpha_target)
```

The sender MUST compute:

```text
step_size = clamp(1, K, round_half_up(raw_step))
```

Where:

1. `round_half_up(x)` means nearest integer, with `.5` ties rounded upward
2. `clamp(1, K, value)` restricts result to `[1, K]`

Then define:

1. `effective_overlap = K - step_size`
2. `effective_overlap_ratio = effective_overlap / K`

### 9.3 Generation Boundaries

For generation index `g >= 0`:

1. `generation_start[g] = g * step_size`
2. `generation_end_exclusive[g] = generation_start[g] + K`

Generation membership is the integer interval:

```text
[generation_start[g], generation_end_exclusive[g])
```

### 9.4 No Fractional Geometry

The following are forbidden in normative text and examples:

1. fractional generation starts
2. fractional step sizes
3. fractional effective overlap values
4. "approximately N symbols" as actual boundary rule

Fractional overlap ratios MAY appear only as configuration intent, never as runtime generation boundaries.

### 9.5 Integer Examples

#### Robust profile example

1. `K = 16`
2. `alpha_target = 0.25`
3. `raw_step = 12.0`
4. `step_size = 12`
5. `effective_overlap = 4`

Generations:

1. `g0 = [0, 16)`
2. `g1 = [12, 28)`
3. `g2 = [24, 40)`

#### Balanced profile example

1. `K = 24`
2. `alpha_target = 0.125`
3. `raw_step = 21.0`
4. `step_size = 21`
5. `effective_overlap = 3`

Generations:

1. `g0 = [0, 24)`
2. `g1 = [21, 45)`
3. `g2 = [42, 66)`

#### Throughput profile example

1. `K = 30`
2. `alpha_target = 0.0`
3. `raw_step = 30.0`
4. `step_size = 30`
5. `effective_overlap = 0`

Generations:

1. `g0 = [0, 30)`
2. `g1 = [30, 60)`
3. `g2 = [60, 90)`

## 10. Realization Identity and Dedup Rules

The realization layer is optional. If present, it MUST remain below semantic identity.

### 10.1 Identity Levels

The specification recognizes three identity levels:

1. semantic unit identity
2. realization identity
3. transport frame identity

They MUST remain distinct.

### 10.2 Semantic Unit Identity

For `SYSTEMATIC`:

```text
(generation_id, source_index)
```

For `CODED`:

```text
(generation_id, equation_id)
```

### 10.3 Realization Identity

If realization diversity is used:

```text
realization_identity = (semantic_unit_identity, realization_index)
```

Rules:

1. realization identity MUST refine semantic identity, not replace it
2. different realizations of the same semantic unit MUST preserve the same semantic unit identity
3. same systematic unit across realizations MUST preserve `(generation_id, source_index)`
4. same coded equation across realizations MUST preserve `(generation_id, equation_id)`

### 10.4 Transport Frame Identity

Transport frame identity, such as `transport_frame_id`, MAY be carried for:

1. ordering
2. replay logs
3. transport statistics

It MUST NOT be used for:

1. systematic deduplication
2. coded deduplication
3. equation identity
4. generation completion logic

### 10.5 Realization Count Semantics

Let `D_available` be the number of realizations available for a semantic unit under a transport profile.

`D_available` means only:

1. how many distinct visual realizations can be generated

It does **not** mean:

1. every semantic unit MUST be transmitted exactly `D_available` times
2. every realization MUST be used before moving to another semantic unit

Actual realization usage is determined by realization scheduling policy.

### 10.6 Receiver Deduplication Rule

Receiver deduplication MUST operate on semantic identity, not realization identity.

Therefore:

1. same `(generation_id, source_index)` -> duplicate systematic unit
2. same `(generation_id, equation_id)` -> duplicate coded unit
3. different `realization_id` values do not create new semantic information

A receiver MAY track per-realization statistics, but such tracking MUST NOT change semantic acceptance rules.

## 11. Transport Binding Requirements

Transport is not the semantic authority for OGRB. It is a carriage layer.

### 11.1 Binding Rule

The transport binding MUST expose enough decoded metadata to reconstruct exactly one `TransmissionUnit` on successful data-frame decode.

This metadata MAY be carried through:

1. explicit transport header fields
2. payload envelope fields
3. generation control context
4. transport-specific control channels

The semantic authority remains the information layer.

### 11.2 Required Semantic Carriage

The binding MUST make the following semantic fields available to the receiver normalization step:

1. `session_id`
2. `generation_id`
3. `generation_size`
4. `unit_type`
5. `payload_size`
6. `source_index` for `SYSTEMATIC`
7. `equation_id` for `CODED`
8. `coding_seed` and `degree` for `CODED`
9. optional `realization_id` if realization diversity is enabled

### 11.3 Binding Restrictions

The binding MUST NOT:

1. redefine semantic identity
2. merge `source_index` and `equation_id`
3. use `transport_frame_id` as semantic identity
4. reinterpret invalid payloads as degraded semantic units

## 12. Receiver Architecture

The receiver MUST preserve the layer boundary internally:

```text
capture frame
-> visual decode
-> validate frame
-> build TransmissionUnit or discard as erasure
-> information-layer ingest
-> generation state update
-> decode attempt
```

### 12.1 Per-Generation State

Receiver per-generation state MUST include at least:

```python
class GenerationState:
    generation_id: int
    generation_size: int
    systematic_symbols: dict[int, bytes]
    coded_equations: dict[int, Equation]
    received_source_ids: set[tuple[int, int]]
    received_equation_ids: set[tuple[int, int]]
    decode_complete: bool
    last_progress_ts: float
```

### 12.2 Decode Triggering

Receiver SHOULD attempt decode after acceptance of any new semantic information:

1. a new `SYSTEMATIC` unit
2. a new `CODED` unit

Receiver MAY throttle decode attempts, but correctness MUST NOT depend on transport-frame timing.

### 12.3 Decoding Semantics

Direct completion:

```python
if len(gen.systematic_symbols) == gen.generation_size:
    return materialize_in_order(gen.systematic_symbols)
```

Otherwise:

1. systematic units are known variables
2. coded units are equations
3. rank growth and recovery depend on equations, not on raw frame count

## 13. Sender Algorithm

This section defines the baseline sender algorithm.

### 13.1 Inputs

A baseline sender requires:

1. source data partitioned into generations
2. integer `generation_size = K`
3. configured systematic prefix `P_sys`
4. configured fresh coded budget `B_code_new`
5. configured drain budget `B_drain_dup`
6. active-generation limit `G_active_max`
7. old/new pool weights `W_old : W_new`
8. optional overlap configuration
9. optional realization scheduling policy

### 13.2 Generation Admission

For each new generation:

1. create generation record in `CREATED`
2. admit it when capacity permits or after deterministic eviction
3. transition to `ACTIVE_SYSTEMATIC`

### 13.3 Systematic Phase

In `ACTIVE_SYSTEMATIC`:

1. sender MUST emit each configured systematic-prefix unit at least once
2. the baseline prefix rule is:

```text
source_index in [0, P_sys)
```

3. if `P_sys == K`, baseline behavior is full systematic-first
4. if `P_sys < K`, only the configured prefix is guaranteed before coded phase

### 13.4 Coded Phase

After the systematic-prefix obligation is satisfied:

1. transition to `ACTIVE_CODED`
2. generate and emit fresh coded equations until `B_code_new` is exhausted
3. each fresh equation MUST receive a new `equation_id`

### 13.5 Draining Phase

When `B_code_new` is exhausted:

1. if `B_drain_dup > 0`, transition to `DRAINING`
2. else transition directly to `EXPIRED`

In `DRAINING`, sender MAY emit duplicate retransmissions of previously emitted semantic units only.

### 13.6 Overlap

If overlap is enabled:

1. generation construction determines membership
2. scheduling still operates on generation lifecycle states
3. overlap MUST NOT alter semantic identity rules

## 14. Receiver Algorithm

This section defines the baseline receiver algorithm.

### 14.1 Per-Frame Processing

For each captured frame:

1. perform visual decode
2. if invalid, discard as erasure
3. if valid data frame, build exactly one `TransmissionUnit`
4. route by `generation_id`
5. apply semantic deduplication using:
   - `(generation_id, source_index)` for `SYSTEMATIC`
   - `(generation_id, equation_id)` for `CODED`
6. update generation state
7. attempt decode according to local trigger policy

### 14.2 Duplicate Handling

Receiver MUST distinguish:

1. duplicate systematic unit
2. duplicate coded equation
3. fresh but algebraically redundant coded equation

Only the first two are semantic duplicates.

### 14.3 Realization Handling

If two different frames carry two different realizations of the same semantic unit:

1. first accepted semantic unit counts
2. later accepted realizations of that same semantic unit are duplicates
3. receiver MAY record realization-level statistics
4. receiver MUST NOT count multiple realizations as multiple semantic units

## 15. Three Core Trade-Offs

OGRB tuning is governed by three core trade-offs.

### 15.1 Forward Progress

Forward progress is the rate at which sender airtime reaches newer source data.

Forward progress increases with:

1. larger `W_new`
2. smaller overlap
3. smaller `B_drain_dup`
4. smaller `D_available` usage

### 15.2 Revisit Pressure

Revisit pressure is the rate at which incomplete generations receive additional transmission opportunities.

Revisit pressure increases with:

1. larger `W_old`
2. larger overlap
3. larger `B_code_new`
4. larger `B_drain_dup`

### 15.3 Recovery Robustness

Recovery robustness is the probability that a generation becomes decodable under erasures and realization-dependent failures.

Recovery robustness increases with:

1. larger `P_sys`
2. larger `B_code_new`
3. larger `effective_overlap`
4. better realization diversity policy

These three goals are not independent. Increasing one usually reduces at least one of the others.

## 16. Operating Profiles

The baseline defines three operating profiles.

All profile parameters below are runtime integers or deterministic ratios.

### 16.1 Robust

Target:

1. high erasure rate
2. low sender FPS
3. completion probability over throughput

Recommended parameters:

1. `K = 16`
2. `alpha_target = 0.25`
3. `step_size = 12`
4. `effective_overlap = 4`
5. `P_sys = 4`
6. `B_code_new = 12`
7. `B_drain_dup = 4`
8. `G_active_max = 2`
9. `W_old : W_new = 2 : 1`
10. `D_available = 2`

### 16.2 Balanced

Target:

1. moderate erasure rate
2. moderate sender/capture FPS mismatch
3. balanced throughput and recovery

Recommended parameters:

1. `K = 24`
2. `alpha_target = 0.125`
3. `step_size = 21`
4. `effective_overlap = 3`
5. `P_sys = 6`
6. `B_code_new = 8`
7. `B_drain_dup = 2`
8. `G_active_max = 2`
9. `W_old : W_new = 3 : 2`
10. `D_available = 1`

### 16.3 Throughput

Target:

1. low erasure rate
2. high sender FPS
3. throughput over robustness

Recommended parameters:

1. `K = 30`
2. `alpha_target = 0.0`
3. `step_size = 30`
4. `effective_overlap = 0`
5. `P_sys = 10`
6. `B_code_new = 4`
7. `B_drain_dup = 0`
8. `G_active_max = 1`
9. `W_old : W_new = 1 : 1`
10. `D_available = 1`

## 17. Parameter Quick Reference

| Parameter | Meaning | Type | Baseline role |
|---|---|---|---|
| `K` | generation size | integer | source symbols per generation |
| `alpha_target` | configured overlap ratio | rational input | converted to integer geometry |
| `step_size` | generation step | integer | sender construction |
| `effective_overlap` | overlap in symbols | integer | sender construction |
| `P_sys` | systematic prefix size | integer | first-transmission obligation |
| `B_code_new` | fresh coded budget | integer | fresh coded injection limit |
| `B_drain_dup` | duplicate replay budget | integer | draining replay limit |
| `G_active_max` | max active generations | integer | active-set limit |
| `W_old` | old-pool weight | integer | fair scheduling |
| `W_new` | new-pool weight | integer | fair scheduling |
| `D_available` | available realization count | integer | optional visual diversity only |

## 18. Performance Metrics

An implementation SHOULD report metrics that respect semantic identity.

### 18.1 Sender Metrics

1. generations created
2. generations admitted
3. generations expired
4. generations evicted
5. fresh coded equations emitted
6. duplicate coded replays emitted
7. duplicate systematic replays emitted
8. active-set occupancy over time

### 18.2 Receiver Metrics

1. generations completed
2. decode latency per generation
3. duplicate systematic rate
4. duplicate coded rate
5. redundant but non-duplicate coded rate
6. rank growth over time
7. recovered source-symbol count

### 18.3 Derived Efficiency Metrics

1. generation success rate
2. median generation decode latency
3. redundancy efficiency
   - recovered source symbols per fresh coded equation
4. duplicate equation rate
   - duplicate coded receptions / total coded receptions
5. realization efficiency, if enabled
   - semantically accepted units / total realization transmissions

## 19. Scheduler Compliance Requirements

A sender is OGRB-compliant only if all of the following are true.

### 19.1 Systematic Prefix Compliance

For every generation, the sender MUST emit every configured systematic-prefix unit at least once before emitting the first fresh coded equation of that generation.

### 19.2 Coded Identity Compliance

For every generation:

1. every fresh coded equation MUST use a distinct `equation_id`
2. every duplicate retransmission of the same coded equation MUST preserve the same `equation_id`
3. the sender MUST NOT map two different equations onto the same `(generation_id, equation_id)`

### 19.3 Replay Compliance

The sender MUST distinguish:

1. fresh coded injection
2. duplicate coded replay
3. duplicate systematic replay

These behaviors MUST be counted separately in sender metrics.

### 19.4 Active-Set Compliance

The sender MUST:

1. enforce `G_active_max`
2. admit new generations deterministically
3. evict generations only by deterministic eviction rule
4. remove terminal generations from the active set immediately

### 19.5 Fairness Compliance

The sender MUST provide finite service to every eligible active generation.

A sender that can permanently starve an eligible generation is non-compliant.

### 19.6 Terminal-State Compliance

A generation in `COMPLETED`, `EXPIRED`, or `EVICTED` MUST NOT be scheduled again.

### 19.7 Realization Compliance

If realization diversity is enabled:

1. realization selection MUST NOT change semantic identity
2. duplicate realizations MUST remain duplicates at the semantic layer
3. the sender MUST NOT require that all available realizations be emitted

### 19.8 Transport Independence

The scheduler MUST operate on semantic units, not transport frames.

A compliant scheduler MUST NOT use `transport_frame_id` as a proxy for semantic identity or replay state.

## 20. Design Invariants

The following invariants are mandatory.

### 20.1 Layer Separation

1. information layer defines semantic units
2. scheduling layer schedules semantic units
3. transport layer carries semantic units

### 20.2 Identity Separation

1. `SYSTEMATIC` identity is `(generation_id, source_index)`
2. `CODED` identity is `(generation_id, equation_id)`
3. realization identity is subordinate to semantic identity
4. transport frame identity is not semantic identity

### 20.3 Erasure Discipline

1. invalid frame -> erasure
2. invalid frame MUST NOT partially update state
3. invalid frame MUST NOT enter deduplication

### 20.4 Sender Lifecycle Discipline

1. sender scheduling state is not receiver decode state
2. no-feedback baseline sender MUST NOT claim completion
3. terminal sender states MUST terminate scheduling

### 20.5 Integer Geometry Discipline

1. runtime generation boundaries MUST be integers
2. fractional overlap is configuration intent only
3. examples MUST use integerized geometry

## Appendix A. Consistency Checklist

1. semantic unit identity, realization identity, and transport frame identity are all defined separately
2. no primary `known_symbols: Set[int]` model is used
3. sender lifecycle and receiver decode lifecycle are described separately
4. baseline no-feedback sender does not enter `COMPLETED`
5. replay semantics distinguish:
   - identical systematic replay
   - identical coded replay
   - fresh coded injection
6. semantic novelty and algebraic innovation are described separately
7. baseline OGRB is described as bounded rateless-style scheduling
8. all normative geometry examples use integer `step_size` and integer `effective_overlap`
9. realization diversity does not alter semantic identity
10. `D_available` is not treated as a rigid transmission multiplier
11. active-set limit, fairness, eviction, and terminal removal are all explicit
12. transport binding is not the semantic authority for OGRB
