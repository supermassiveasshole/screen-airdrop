# OGRB Protocol Specification

Version: 3.0-draft  
Status: Design draft  
Target system: Screen-Airdrop visual transmission pipeline

## 1. Introduction

This document specifies the OGRB protocol family for Screen-Airdrop.

OGRB is not a visual renderer. OGRB is not a frame format by itself. OGRB is a scheduling model that operates on explicitly defined transmission units and relies on a separate visual transport layer to carry them over a real screen-capture channel.

The purpose of this rewrite is to make the protocol implementable without semantic ambiguity. In particular, it enforces:

1. strict separation between information semantics, scheduling, and visual transport
2. explicit distinction between systematic symbols and coded equations
3. an erasure-oriented channel model for real-world screen capture failure modes
4. compatibility with existing Screen-Airdrop visual designs, especially layered rendering, compact control headers, and gray4 modulation

This specification does not require erasure coding to be implemented immediately. It defines the architecture so that Phase 4 (erasure coding) and Phase 5 (OGRB scheduling) can be added without redesigning the visual layer again.

## 2. System Overview

The system is defined as three strictly separated layers.

### 2.1 Layer 1: Information Layer

This layer defines **what** is being transmitted.

Its output is a stream of `TransmissionUnit` objects. A `TransmissionUnit` is either:

1. `SYSTEMATIC`
   A source symbol from a generation.
2. `CODED`
   A coded equation over source symbols of a generation.

This layer owns:

1. generation semantics
2. source symbol identity
3. coded equation identity
4. decoding semantics

This layer does **not** define frame timing, visual layout, or modulation.

### 2.2 Layer 2: Scheduling Layer

This layer defines **when** each `TransmissionUnit` is sent.

This is the OGRB layer. It decides:

1. which generation is active
2. how new and old generations are mixed
3. when revisits occur
4. how much redundancy is allocated
5. whether overlapping generations are enabled

This layer operates on `TransmissionUnit` objects only. It must not redefine their meaning.

### 2.3 Layer 3: Visual Transport Layer

This layer defines **how** a `TransmissionUnit` is rendered to the screen and recovered from captured frames.

This specification preserves the existing visual design directions:

1. compact control header encoding
2. layered header/payload separation
3. gray4 visual modulation
4. existing protocol adaptor abstraction

This layer is semantics-agnostic. It transports `TransmissionUnit` objects but does not define whether a payload is a source symbol or a coded equation.

### 2.4 Layer Relation

The relation between the layers is:

1. Information layer defines the units.
2. OGRB schedules those units.
3. Visual transport carries those units.

Explicitly:

1. erasure coding is not a subset of OGRB
2. OGRB depends on information units that are suitable for erasure recovery
3. the visual layer is below both and must not invent protocol semantics

## 3. Channel Model & Robustness Assumptions

Screen-Airdrop does not run on an ideal packet channel. It runs on a visual channel with asynchronous sampling and display composition.

Typical path:

```text
sender renderer -> local compositor -> remote desktop / video compression
-> receiver screen capture -> frame decode
```

### 3.1 Real-World Failure Modes

The channel may exhibit:

1. tearing
   The captured image contains a mixture of two rendered frames.
2. frame skip / drop
   A displayed frame is never captured or never successfully decoded.
3. asynchronous capture
   Capture occurs at arbitrary times relative to sender frame boundaries.
4. decode failure
   Header or payload cannot be decoded reliably.

### 3.2 Required Abstraction

All channel failures must be mapped to the same abstract outcome:

**ERASURE**

That means:

1. a valid frame yields exactly one valid `TransmissionUnit`
2. an invalid frame yields no `TransmissionUnit`
3. corrupted frames must never partially update decoder state

### 3.3 Strong Receiver Rule

A frame must either be fully accepted as a valid `TransmissionUnit` or completely discarded as an erasure. It must not partially influence system state.

Consequences:

1. corrupted headers must be discarded immediately
2. invalid payloads must be discarded immediately
3. partial payload reuse is forbidden
4. invalid frames must not participate in deduplication
5. invalid frames must not create generation state

### 3.4 Robustness Strategy

Robustness is achieved by converting all channel errors into erasures and relying on erasure coding for recovery.

This is the central protocol assumption.

The visual layer may use CRC, ECC, geometry checks, or confidence thresholds to classify frames as valid or invalid. But once a frame is classified invalid, it is an erasure, not a degraded symbol.

## 4. Information Layer (Generation + Erasure Coding)

This layer defines the semantic transmission objects.

### 4.1 Terminology

Use these terms consistently:

1. `source symbol`
   A fixed-size chunk of original source data.
2. `coded equation`
   A linear equation over source symbols of one generation.
3. `TransmissionUnit`
   The semantic object carried by the visual layer.
4. `frame`
   A visual transport container. A frame carries one `TransmissionUnit`.

Do not use `symbol`, `unit`, and `frame` interchangeably.

### 4.2 Generation Model

Source data is partitioned into generations.

Each generation has:

1. `generation_id`
2. `generation_size = K`
3. ordered source symbols with local indices `0 .. K-1`

Generation completion means:

1. all source symbols of that generation are known
2. therefore the generation can be materialized as ordered source bytes

Symbol Size Invariant:

All source symbols within a generation MUST have the same fixed size.

For every `TransmissionUnit` in a generation:

```text
payload_size MUST equal symbol_size
```

Variable payload sizes within a generation are not supported unless explicitly specified by a future extension.

### 4.3 TransmissionUnit

```text
TransmissionUnit =
    SystematicUnit
  | CodedUnit
```

#### 4.3.1 SystematicUnit

Represents one source symbol.

Fields:

1. `unit_type = SYSTEMATIC`
2. `generation_id`
3. `generation_size`
4. `source_index`
5. `payload`

Identity:

```text
(generation_id, source_index)
```

#### 4.3.2 CodedUnit

Represents one coded equation over source symbols in one generation.

Fields:

1. `unit_type = CODED`
2. `generation_id`
3. `generation_size`
4. `equation_id`
5. `coding_seed` or explicit coefficient description
6. `degree`
7. `payload`

Identity:

```text
(generation_id, equation_id)
```

### 4.4 Identity Rules

The receiver must maintain two separate identity spaces:

1. `received_source_ids`
2. `received_equation_ids`

They must never be merged.

Specifically:

1. `source_index` exists only for `SYSTEMATIC`
2. `equation_id` exists only for `CODED`
3. a coded equation is not a source symbol
4. a coded equation does not occupy `source_index`

The old idea of a universal `symbol_index` for all transmitted objects is invalid and must not be used.

Equation Identity Rule:

For `CODED` units, `equation_id` MUST uniquely identify the equation content within a given `(session_id, generation_id)`.

Two `CODED` units that correspond to the same equation, that is, the same generation, the same coefficient set, and the same coding parameters, MUST use the same `equation_id`.

Different `equation_id` values MUST correspond to different equations.

Sender implementations MUST ensure that repeated transmission of the same coded equation, including different visual realizations, preserves `equation_id`.

Receiver implementations MUST use `(generation_id, equation_id)` as the sole identity key for coded equation deduplication.

### 4.5 Coded vs Systematic Semantics

`SYSTEMATIC` units are direct values of variables.

`CODED` units are constraints over variables.

In algebraic terms:

1. systematic symbol:

```text
x_i = payload
```

2. coded equation:

```text
a_0*x_0 + a_1*x_1 + ... + a_(K-1)*x_(K-1) = payload
```

For XOR-based coding over GF(2^8), coefficients are often binary selection indicators and the operation is XOR.

The critical rule is:

**coded equations are not source symbols**

### 4.6 Equation Representation

An implementation may represent a coded equation as:

```text
equation_id
generation_id
generation_size
coefficient_set
rhs_payload
```

Where:

1. `coefficient_set` may be generated from `coding_seed`
2. `rhs_payload` is the coded payload bytes

The protocol requires that the receiver be able to reconstruct the same equation deterministically from the metadata.

### 4.7 Decoder State Model

For each generation, the receiver maintains:

1. `systematic_symbols: Dict[source_index, payload]`
2. `coded_equations: Dict[equation_id, Equation]`
3. `generation_size`
4. `decode_complete`

The receiver must not use a single set such as:

```python
known_symbols: Set[int]
```

as the primary semantic state.

The correct model is:

```python
systematic_symbols: Dict[int, bytes]
coded_equations: Dict[int, Equation]
received_source_ids: Set[tuple[int, int]]
received_equation_ids: Set[tuple[int, int]]
```

### 4.8 Receiver Acceptance Logic

Pseudocode:

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

    raise ProtocolError("unknown unit type")
```

## 5. Scheduling Layer (OGRB)

OGRB is the scheduling layer. It operates over `TransmissionUnit` objects. It does not define symbol semantics.

### 5.1 Scheduling Goals

OGRB exists to balance:

1. forward progress into new data
2. revisit pressure for incomplete generations
3. bounded decoding latency
4. tolerance to erasures without feedback

### 5.2 Active Generations

The sender maintains an active generation set.

Each active generation may emit:

1. systematic units
2. coded units

The scheduler chooses among active generations based on policy.

### 5.3 New vs Old Generation Mixing

The scheduler may allocate airtime differently to:

1. new generations
2. old incomplete generations

Typical policy knob:

```text
old_new_ratio = airtime(old generations) / airtime(new generations)
```

This controls revisit pressure without changing information semantics.

### 5.4 Revisit Cycles

A revisit cycle is the time between useful opportunities for an incomplete generation to receive another `TransmissionUnit`.

OGRB must be specified in terms of units, not frames.

Correct statement:

```text
OGRB schedules TransmissionUnit emission opportunities for generations.
```

Incorrect statement:

```text
OGRB schedules frames directly.
```

Frames are visual carriers selected later by the transport layer.

### 5.5 Overlap

Generation overlap is optional and applies only to the scheduling/information boundary.

If overlap is enabled:

1. consecutive generations share some source symbols
2. those symbols may be recoverable through more than one generation context

Overlap improves robustness but increases schedule complexity and can reduce net forward progress.

### 5.6 Redundancy Allocation

The scheduler may allocate redundancy by:

1. increasing systematic retransmission frequency
2. increasing coded equation emission rate
3. favoring old generations longer
4. increasing overlap

This is an OGRB concern. It does not redefine what a coded equation means.

### 5.7 OGRB Scheduling Skeleton

Pseudocode:

```python
def next_transmission(active_generations, policy):
    gen = policy.select_generation(active_generations)

    if policy.should_send_systematic(gen):
        unit = gen.next_systematic_unit()
    else:
        unit = gen.next_coded_unit()

    return unit
```

If overlap is enabled, generation construction decides membership. OGRB only schedules the resulting units.

## 6. Visual Transport Layer

This layer carries `TransmissionUnit` objects over a screen-render/capture channel.

It is explicitly semantics-agnostic.

### 6.1 Responsibilities

The visual transport layer is responsible for:

1. rendering unit metadata and payload into a visual frame
2. preserving sync and locator structures
3. recovering metadata and payload from captured images
4. validating that a frame is trustworthy enough to yield exactly one `TransmissionUnit`

It is not responsible for:

1. generation completion
2. equation solving
3. OGRB scheduling
4. deciding whether a unit is systematic or coded in a semantic sense beyond the header field

Transport Semantics Boundary:

The transport layer carries information-layer metadata fields, such as `generation_id`, `source_index`, `equation_id`, and coding parameters, but MUST NOT interpret, modify, or redefine their semantics.

All semantic meaning of these fields is defined exclusively by the information layer.

### 6.2 Existing Screen-Airdrop Design Decisions to Preserve

The following are part of the current design and remain valid:

1. compact control header encoding
2. gray4 modulation as a supported visual encoding mode
3. layered rendering, where header/control information and payload information are visually separated
4. protocol adaptor abstraction, so multiple visual encodings can carry the same `TransmissionUnit`

### 6.3 Layered Rendering

Layered rendering is preserved.

The meaning is:

1. a frame has a control/header region or control/header layer
2. a frame has a payload-bearing region or payload layer
3. header recovery should fail closed
4. payload is interpreted only after header validation succeeds

This separation is transport-level. It must not redefine the meaning of systematic versus coded units.

### 6.4 Compact Encoding

Compact encoding is the preferred header transport when control metadata must be kept small and robust.

It should carry:

1. unit type
2. generation metadata
3. unit identity metadata
4. coding metadata for coded units
5. checksums / CRC

### 6.5 Gray4 Modulation

Gray4 is a transport modulation choice.

It affects:

1. visual density
2. symbol raster layout
3. decode sensitivity to blur/compression

It does not affect:

1. `TransmissionUnit` identity rules
2. generation semantics
3. OGRB scheduling

### 6.6 Transport Contract

The transport contract is:

```text
Frame decode success -> exactly one TransmissionUnit
Frame decode failure -> erasure
```

No third outcome is allowed.

## 7. Frame Format (updated header fields)

Each visual frame carries exactly one `TransmissionUnit`.

### 7.1 Required Header Fields

The transport header must include at minimum:

| Field | Type | Meaning |
|---|---|---|
| `session_id` | uint32 | transmission session identifier |
| `transport_frame_id` | uint64 | monotonic visual frame sequence |
| `unit_type` | uint8 | `SYSTEMATIC` or `CODED` |
| `generation_id` | uint32 | generation identifier |
| `generation_size` | uint16 | K |
| `payload_size` | uint16 | bytes carried in this unit |
| `source_index` | uint16 or null | valid only for `SYSTEMATIC` |
| `equation_id` | uint32 or null | valid only for `CODED` |
| `coding_seed` | uint32 or null | valid only for `CODED` |
| `degree` | uint8 or null | valid only for `CODED` |
| `header_crc` | uint16/uint32 | integrity of header |
| `payload_crc` | uint16/uint32 | integrity of payload |

### 7.2 Header Semantics

Rules:

1. `source_index` must be present only when `unit_type == SYSTEMATIC`
2. `equation_id` must be present only when `unit_type == CODED`
3. `coding_seed` and `degree` must be present only when `unit_type == CODED`
4. `source_index` and `equation_id` must never be overloaded into a single generic field

### 7.3 Header Validation

Receiver pipeline:

1. recover header candidates
2. validate `header_crc`
3. reject the frame immediately if header is invalid
4. recover payload only after header acceptance
5. validate `payload_crc`
6. yield `TransmissionUnit` only if both are valid

### 7.4 Optional Visual Metadata

The transport may include additional fields such as:

1. adaptor version
2. modulation mode
3. layout profile
4. realization identifier if visual diversity is added later

These are transport concerns and must not replace the information-layer identifiers.

## 8. Receiver Architecture

The receiver must preserve the three-layer separation internally.

### 8.1 Receiver Pipeline

```text
capture frame
-> visual decode
-> validate frame
-> build TransmissionUnit or discard as erasure
-> information-layer ingest
-> generation state update
-> generation decode attempt
```

### 8.2 Visual Decode Stage

The visual decode stage may use:

1. layered header extraction
2. compact header decoding
3. gray4 symbol demodulation
4. existing protocol adaptors

Its output must be:

1. valid `TransmissionUnit`
2. or erasure

### 8.3 Information-Layer Ingest

The information-layer ingest stage must:

1. route by `generation_id`
2. split `SYSTEMATIC` and `CODED`
3. track `received_source_ids`
4. track `received_equation_ids`
5. reject duplicates independently in each identity space

### 8.4 State Model per Generation

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

### 8.5 Processing Logic

```python
def process_frame(frame):
    unit = visual_transport_decode(frame)
    if unit is ERASURE:
        return

    result = information_layer_accept(unit)
    if result in (ACCEPTED, DUPLICATE):
        maybe_decode_generation(unit.generation_id)
```

Invalid frames do not enter deduplication, do not create partial state, and do not influence decode.

## 9. Decoding Algorithms

### 9.0 Decode Triggering

The receiver MUST define when decoding attempts are performed.

Baseline rule:

1. The receiver SHOULD attempt decoding after accepting any new information:
   - a new `SYSTEMATIC` unit
   - a new `CODED` unit

2. The receiver MAY throttle decode attempts:
   - e.g., perform decode only every N accepted units
   - or every T milliseconds

3. The receiver SHOULD skip decode if no new information has been accepted since the last attempt.

Decode triggering policy does not affect correctness, but strongly affects latency and computational cost.

### 9.1 Direct Completion

If all systematic symbols are known:

```python
if len(gen.systematic_symbols) == gen.generation_size:
    return materialize_in_order(gen.systematic_symbols)
```

### 9.2 Peeling Decoding

Peeling decoding applies when equations are sparse.

Representation:

```python
Equation:
    variables: set[int]
    rhs: bytes
```

Reduction rule:

1. if some variables are already known, eliminate them from the equation
2. if an equation has exactly one unknown variable left, solve it
3. insert that solved symbol into `systematic_symbols`
4. repeat until no progress is possible

Pseudocode:

```python
def peeling_decode(gen):
    known = dict(gen.systematic_symbols)
    pending = list(gen.coded_equations.values())

    changed = True
    while changed:
        changed = False
        for eq in pending:
            eq = eliminate_known(eq, known)
            if len(eq.variables) == 1:
                idx = only_element(eq.variables)
                if idx not in known:
                    known[idx] = eq.rhs
                    changed = True

    if len(known) == gen.generation_size:
        gen.systematic_symbols = known
        gen.decode_complete = True
```

### 9.3 General Linear Solve

If the code family later uses denser equations, the receiver may switch from peeling to Gaussian elimination or another solver over the appropriate finite field.

The semantic model does not change:

1. systematic units are known variables
2. coded units are equations

### 9.4 Independence of Equations

Multiple coded equations may be redundant.

Receiver must not assume:

1. every coded unit adds new information
2. every received equation is independent

Instead, decode progress depends on equation rank or peeling usefulness.

### 9.5 Duplicate and Redundant Units

Duplicate handling:

1. same `(generation_id, source_index)` -> duplicate systematic unit
2. same `(generation_id, equation_id)` -> duplicate coded unit

Redundant but non-duplicate coded equations are still valid. They may fail to increase rank, but they must not be collapsed into source-symbol identity space.

## 10. Design Principles & Invariants

The following invariants are mandatory.

### 10.1 Layer Separation

1. information layer defines semantic units
2. OGRB schedules semantic units
3. visual transport carries semantic units

No layer may silently absorb the responsibilities of another.

### 10.2 Identity Separation

1. `SYSTEMATIC` identity is `(generation_id, source_index)`
2. `CODED` identity is `(generation_id, equation_id)`
3. these identity spaces must remain separate

### 10.3 Decoding Semantics

1. systematic symbols are known variables
2. coded equations are constraints
3. coded equations are not source symbols

### 10.4 Erasure Discipline

1. every invalid frame is an erasure
2. invalid frames must not partially affect system state
3. no partial reuse of corrupted payload is allowed

### 10.5 Transport Agnosticism

1. layered rendering is preserved
2. gray4 is preserved as a transport option
3. compact headers are preserved
4. none of these transport choices may redefine information semantics

### 10.6 Scheduling Agnosticism

OGRB must not redefine symbol meaning. It chooses emission order and redundancy only.

### 10.7 Engineering Rule

If an implementation detail makes it difficult to maintain the distinction between:

1. `SYSTEMATIC` vs `CODED`
2. unit identity vs frame identity
3. valid frame vs erasure

that implementation detail is wrong and must be changed.
