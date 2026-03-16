# OGRB Protocol Specification v2

**OGRB (Overlapping Generation Rateless Broadcast)**

Version: 2.0
Status: Draft
Date: 2026-03-15

---

## 1. Introduction

### 1.1 Purpose

This document specifies the OGRB (Overlapping Generation Rateless Broadcast) protocol version 2 for Screen-Airdrop. OGRB is designed to provide efficient, robust data transmission over visual broadcast channels with packet loss, decode failures, and limited feedback.

### 1.2 What's New in v2

Version 2 introduces several architectural enhancements while maintaining backward compatibility with v1 concepts:

1. **Realization Layer**: Visual diversity mechanisms to combat pattern-dependent decode failures
2. **Policy Layer**: Optional ML-driven adaptive control
3. **Enhanced Architecture**: Five-layer model for independent evolution
4. **Realization Diversity**: Multiple visual representations per logical symbol

### 1.3 Scope

OGRB is not a single fixed-parameter protocol but a family of configurable operating points. It enables different trade-offs between:

- Recovery success rate
- Revisit pressure control
- Maximum throughput
- Robustness to visual channel impairments

### 1.4 Visual Communication Channel Model

OGRB is specifically designed for **visual communication channels** such as screen-to-camera or remote desktop pipelines.

Typical channel path:

```
display → compositor → remote desktop → compression → capture → decoding
```

These channels differ from traditional packet networks because they exhibit:

- Frame loss (dropped frames)
- Decode failure instead of packet corruption
- Realization-dependent decoding success (same data, different visual patterns → different success rates)
- Absence of reliable feedback
- Pattern-dependent failures due to blur, compression, sampling, color conversion

### 1.5 Design Philosophy

OGRB addresses the limitations of frame-by-frame sequential transmission by:

1. Treating each frame as a lightweight symbol carrier
2. Moving primary recovery responsibility from frame-internal ECC to cross-frame erasure coding
3. Supporting mid-session join and continuous recovery through rateless coding
4. Maintaining short revisit cycles through overlapping generations
5. **NEW in v2**: Introducing visual realization diversity to mitigate pattern-dependent failures

### 1.6 Why Not Whole-File Fountain Codes

OGRB deliberately avoids whole-file fountain coding because:

- Decoding complexity scales poorly with file size
- Time-to-first-recovery is too long for interactive use
- Revisit cycles become uncontrollable
- Debugging and tuning complexity is excessive

Instead, OGRB uses small generations with limited overlap, providing:

- Fast per-generation recovery
- Predictable revisit cycles
- Manageable decoder complexity
- Clear progress indicators

### 1.7 Deterministic Engineering First

The protocol is designed for **deterministic engineering first**, with optional ML augmentation later. Core mechanisms are based on well-understood coding theory and scheduling heuristics, while ML components are isolated in optional policy layers.

---

## 2. Normative Language

This specification uses RFC 2119 terminology:

- **MUST**: Absolute requirement
- **MUST NOT**: Absolute prohibition
- **SHOULD**: Recommended unless valid reason exists
- **SHOULD NOT**: Not recommended unless valid reason exists
- **MAY**: Optional

---

## 3. Architecture

### 3.1 Five-Layer Structure

OGRB v2 is structured as five independent layers that MUST be kept separate:

```
Layer 0  Physical Frame Layer
Layer 1  Realization Layer (NEW in v2)
Layer 2  Generation Coding Layer
Layer 3  Broadcast Scheduling Layer
Layer 4  Policy Layer (NEW in v2, optional ML)
```

Each layer is designed to evolve independently.

#### Layer 0: Physical Frame Layer

**Responsibilities:**
- Frame capture from visual channel
- ROI (Region of Interest) extraction
- Header decode
- Payload decode
- CRC validation
- Deliver payload if trustworthy
- Treat bad frames as erasures

**Outputs:**
```
decoded symbol
or
symbol erasure
```

**Non-responsibilities:**
- Cross-generation recovery
- Broadcast scheduling
- Global file completion judgment
- Protocol-level recovery logic

**Important**: This layer MUST NOT attempt protocol recovery.

#### Layer 1: Realization Layer (NEW in v2)

**Purpose**: Introduces **visual diversity** to combat pattern-dependent decode failures.

**Concept**: A single logical symbol may be transmitted using multiple visual realizations.

**Responsibilities:**
- Generate multiple visual representations of the same logical symbol
- Apply diversity mechanisms (mask divergence, permutation, whitening)
- Track realization metadata

**Example realizations:**
```
mask divergence
symbol permutation
spatial tile permutation
payload whitening
```

**Goal**: Reduce pattern-dependent decode failures by providing alternative visual representations.

#### Layer 2: Generation Coding Layer

**Responsibilities:**
- Partition source data into small generations
- Source symbol partitioning
- Systematic symbol generation
- Coded symbol generation (XOR combinations)
- Maintain independent recovery state per generation
- Determine when a generation can be recovered
- Generation decoding

**Non-responsibilities:**
- Assume any specific frame must arrive
- Depend on visible epoch boundaries
- Depend on specific realization success

#### Layer 3: Broadcast Scheduling Layer

**Responsibilities:**
- Decide which generation to transmit
- Choose between systematic and coded symbols
- Allocate airtime between old and new generations
- **NEW in v2**: Select realization for each transmission
- **NEW in v2**: Schedule diversity across realizations

**Non-responsibilities:**
- Frame-level encoding details
- Symbol-level error correction
- Realization generation logic

#### Layer 4: Policy Layer (NEW in v2, Optional)

**Purpose**: Allows adaptive control of protocol parameters.

**Possible implementations:**
```
static heuristics
adaptive algorithms
ML policy networks
```

**The policy layer may adjust:**
```
realization selection
redundancy level
generation scheduling
mask policy
systematic vs coded ratio
```

**Examples of ML-driven control:**
- Symbol classifier confidence → realization selection
- Header classifier → mask policy adjustment
- Channel quality estimator → redundancy tuning
- Generation completion predictor → scheduling policy

**Important**: This layer operates **above the protocol layer** and is entirely optional.

### 3.2 Layer Separation Requirements

Implementations MUST maintain clear boundaries:

1. Physical frame layer MUST NOT perform cross-generation recovery
2. Realization layer MUST NOT make scheduling decisions
3. Generation coding layer MUST NOT depend on specific frame arrival or realization success
4. Broadcast scheduling layer MUST NOT mix with frame encoding logic
5. Policy layer MUST NOT bypass protocol invariants

---

## 4. Core Concepts

### 4.1 Source Symbol

**Definition**: A fixed-size unit of original data.

**Default Size**: 512 bytes

Source data is partitioned into fixed-size symbols. The last symbol is padded if necessary.

### 4.2 Logical Symbol

**Definition**: A logical symbol represents a source symbol within a generation context.

**Key Property**: A logical symbol may appear multiple times through different realizations.

**Example**:
```
Logical symbol 12 in generation 0
  → may be transmitted as realization 0 (mask A)
  → may be transmitted as realization 1 (mask B)
  → may be transmitted as realization 2 (mask C)
```

Receiver only requires **one successful decode** of any realization.

### 4.3 Realization (NEW in v2)

**Definition**: A realization is a specific visual representation of a logical symbol.

**Purpose**: Combat pattern-dependent decode failures by providing visual diversity.

**Mechanism**: Same logical symbol data, different visual encoding parameters.

**Example diversity mechanisms**:
- **Mask divergence**: Different finder pattern masks
- **Symbol permutation**: Reorder data bits before encoding
- **Spatial tile permutation**: Rearrange spatial layout
- **Payload whitening**: XOR with different PRNG sequences

**Parameter**:
```
realization_count = D
```

**Typical values**:
```
D = 1   (diversity disabled, v1 behavior)
D = 2   (two realizations per symbol)
D = 3   (three realizations per symbol)
```

**Receiver behavior**: Accept first successful decode, ignore later duplicates.

### 4.4 Systematic Symbol

**Definition**: A source symbol transmitted without encoding (direct copy of source data).

**Purpose**:
- Reduce latency for early symbols
- Improve decode probability when few symbols received
- Better for receiver sparse sampling scenarios

### 4.5 Coded Symbol

**Definition**: A linear combination (XOR) of multiple source symbols within a generation.

**Generation**: Created by XORing `degree` source symbols selected via PRNG seed.

**Typical degree range**: 2-8 for generation sizes 12-32

### 4.6 Generation

**Definition**: A group of consecutive source symbols that can be independently recovered.

**Parameter**: `generation_size = K`

**Key Properties**:
- Independent decoding unit
- Contains K source symbols
- Can be recovered when sufficient symbols (systematic + coded) are received
- Decoding uses rateless coding (fountain code principles)

### 4.7 Overlapping Generations

**Definition**: Consecutive generations share some symbols in their symbol ranges.

**Parameter**: `generation_overlap = α` (fraction, 0.0 to 0.5)

**Example** (K=20, α=0.25, step=15):
```
Generation 0: symbols [0, 19]
Generation 1: symbols [15, 34]   (overlap: [15, 19])
Generation 2: symbols [30, 49]   (overlap: [30, 34])
```

**Purpose**:
- Provides secondary recovery paths
- Increases revisit opportunities for nearly-complete generations
- Allows symbols to be recovered through multiple generation contexts

**Trade-off**: Overlap increases recovery robustness but reduces forward progress speed.

### 4.8 Symbol Types in Transmission

Each transmitted frame carries either:
- A **systematic symbol** (direct copy of source data)
- A **coded symbol** (XOR combination of multiple source symbols)

Frame also specifies:
- **realization_id** (NEW in v2): Which visual realization is used

---

## 5. Realization Diversity (NEW in v2)

### 5.1 Motivation

Experiments show decoding success can depend on visual pattern realization.

**Observed phenomena**:
- Same data with different visual patterns → different decode success rates
- Failures may occur because patterns interact poorly with:
  - Blur (Gaussian, motion)
  - Compression (JPEG, H.264, H.265)
  - Sampling (subpixel alignment, Moiré patterns)
  - Color conversion (RGB ↔ YUV)

**Solution**: Realization diversity mitigates this effect by providing multiple visual representations of the same logical symbol.

### 5.2 Diversity Mechanisms

#### 5.2.1 Mask Divergence

**Concept**: Use different finder pattern masks for different realizations.

**Example**:
```
Realization 0: mask pattern A
Realization 1: mask pattern B
Realization 2: mask pattern C
```

**Benefit**: Reduces correlation between compression artifacts and specific mask patterns.

#### 5.2.2 Symbol Permutation

**Concept**: Reorder data bits before encoding to visual symbols.

**Example**:
```
Original bits: [b0, b1, b2, ..., b511]
Realization 0: [b0, b1, b2, ..., b511]
Realization 1: [b127, b0, b255, ..., b384]
Realization 2: [b255, b128, b1, ..., b256]
```

**Benefit**: Spreads burst errors across different bit positions.

#### 5.2.3 Spatial Tile Permutation

**Concept**: Rearrange spatial layout of symbol tiles.

**Example**:
```
Realization 0: standard grid order
Realization 1: checkerboard permutation
Realization 2: spiral permutation
```

**Benefit**: Reduces correlation between spatial compression blocks and symbol boundaries.

#### 5.2.4 Payload Whitening

**Concept**: XOR payload with different PRNG sequences.

**Example**:
```
Realization 0: payload ⊕ PRNG(seed=0)
Realization 1: payload ⊕ PRNG(seed=1)
Realization 2: payload ⊕ PRNG(seed=2)
```

**Benefit**: Breaks correlation between payload bit patterns and compression behavior.

### 5.3 Diversity Parameter

**Parameter**: `realization_count = D`

**Recommended values**:
```
D = 1   Diversity disabled (v1 behavior)
        Use when: channel is very clean, throughput is critical

D = 2   Light diversity
        Use when: moderate pattern-dependent failures observed

D = 3   Strong diversity
        Use when: high pattern-dependent failure rate
```

**Trade-off**: Higher D increases airtime cost (more transmissions per logical symbol) but improves recovery probability for problematic symbols.

### 5.4 Realization Scheduling

**Question**: When should different realizations be transmitted?

**Strategies**:

1. **Round-robin**: Cycle through realizations sequentially
2. **Adaptive**: Prioritize realizations with higher historical success rates
3. **ML-driven**: Use policy network to select realization based on channel state

**Default recommendation**: Round-robin for deterministic behavior.

### 5.5 Receiver Realization Handling

**Rule**: Receiver accepts **first successful decode** of a logical symbol, ignores later duplicates.

**State tracking**:
```python
known_symbols: Set[int]  # logical symbol indices

if symbol_index in known_symbols:
    # Already have this symbol, ignore
    return
else:
    # New symbol, accept and add to generation state
    known_symbols.add(symbol_index)
```

**Important**: Receiver does NOT need to track which realization succeeded, only that the logical symbol was recovered.

### 5.6 Future ML-Assisted Mechanisms

Future versions MAY include:
- ML-selected realizations based on channel quality estimator
- Adaptive modulation (different symbol densities per realization)
- Confidence-based realization prioritization

---

## 6. Parameters

### 6.1 Core Parameters

| Parameter | Symbol | Type | Description |
|-----------|--------|------|-------------|
| Symbol Size | `S` | bytes | Size of each source symbol |
| Generation Size | `K` | count | Number of symbols per generation |
| Generation Overlap | `α` | fraction | Overlap between consecutive generations |
| Systematic Prefix | `P` | count | Number of systematic symbols sent first |
| Coded Redundancy | `R` | ratio | Total symbols sent / generation size |
| **Realization Count** | `D` | count | **NEW in v2**: Number of visual realizations per symbol |
| Max Active Generations | `G` | count | Maximum concurrent active generations |
| Old/New Ratio | `β` | ratio | Airtime bias toward older generations |
| Decode Margin | `M` | count | Extra symbols required before decode attempt |

### 6.2 Derived Parameters

**Step Size** (symbols advanced per generation):
```
step_size = K × (1 - α)
```

**Total Symbols per Generation**:
```
total_symbols = K × R
```

**Coded Symbols per Generation**:
```
coded_symbols = K × R - P
```

**Effective Airtime Cost** (NEW in v2, with diversity):
```
effective_transmissions = total_symbols × D
```

### 6.3 Default Parameters

If not otherwise specified, implementations SHOULD start from these values:

```
symbol_size = 512 bytes
generation_size = 20~24
generation_overlap = 0.125~0.25
systematic_prefix = 6~8
coded_redundancy = 1.15~1.25
realization_count = 1~2          # NEW in v2
max_active_generations = 2
old_new_ratio = 1.5
decode_margin = 1
```

### 6.4 Rationale

These defaults represent a **balanced** profile suitable for:
- Local screen capture scenarios
- Limited capture FPS (10-18 fps)
- Moderate packet loss (5-15%)
- Trade-off between throughput and robustness

---

## 7. Frame Model

### 7.1 Frame Structure

Each transmitted frame carries **one symbol realization**.

**Frame contents**:
```
header
  ├─ session_id
  ├─ generation_id
  ├─ generation_start
  ├─ generation_size
  ├─ symbol_size
  ├─ symbol_type (SYSTEMATIC or CODED)
  ├─ symbol_index (for systematic)
  ├─ realization_id (NEW in v2)
  ├─ coding_seed (for coded)
  ├─ degree (for coded)
  ├─ header_crc
  └─ payload_crc
payload
  └─ symbol data (S bytes)
```

**Symbol types**:
```
SYSTEMATIC  (type=0)
CODED       (type=1)
```

### 7.2 Frame Header Format

#### 7.2.1 Required Header Fields

OGRB frame headers SHOULD include at minimum:

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | uint32 | Unique identifier for this transmission session |
| `generation_id` | uint32 | Sequential generation number |
| `generation_start` | uint32 | Global symbol index where this generation starts |
| `generation_size` | uint16 | Number of symbols in this generation (K) |
| `symbol_size` | uint16 | Size of each symbol in bytes |
| `symbol_type` | uint8 | 0=systematic, 1=coded |
| `symbol_index` | uint16 | Index within generation (valid for systematic) |
| **`realization_id`** | **uint8** | **NEW in v2**: Realization index (0 to D-1) |
| `coding_seed` | uint32 | PRNG seed for coded symbol (valid for coded) |
| `degree` | uint8 | Number of source symbols XORed (valid for coded) |
| `header_crc` | uint16 | CRC-16 of header fields |
| `payload_crc` | uint16 | CRC-16 of payload data |

#### 7.2.2 Header Design Requirements

1. **Generation Attribution**: Generation membership MUST be explicitly visible
2. **Symbol Type Distinction**: Systematic vs coded MUST be unambiguous
3. **Realization Identification** (NEW in v2): Realization ID MUST be present
4. **Separate Validation**: Header and payload validity MUST be independently checkable
5. **Compact Encoding**: Header SHOULD fit within control plane capacity

#### 7.2.3 Header vs Payload Validation

Implementations MUST support independent validation:

- **Header Valid, Payload Invalid**: Treat as erasure, count for statistics
- **Header Invalid**: Discard frame immediately, do not attempt payload decode
- **Both Valid**: Accept symbol for generation recovery

---

## 8. Sender Algorithm

### 8.1 Initialization

**Input**: Source file or data stream

**Steps**:
1. Partition data into fixed-size source symbols (pad last symbol if needed)
2. Assign sequential global symbol indices: `0, 1, 2, ..., N-1`
3. Initialize generation scheduler with configured parameters
4. **NEW in v2**: Initialize realization generator with diversity parameters

### 8.2 Generation Partitioning

**Generation Boundaries**:

For generation `g` with size `K` and overlap `α`:

```
step = K × (1 - α)
start[g] = g × step
end[g] = start[g] + K - 1
```

**Example** (K=20, α=0.25, step=15):
```
Generation 0: symbols [0, 19]
Generation 1: symbols [15, 34]
Generation 2: symbols [30, 49]
...
```

### 8.3 Symbol Transmission Sequence

For each generation `g`:

1. **Systematic Phase**: Send `P` systematic symbols
   - Typically send first `P` symbols of the generation
   - Or distribute evenly across generation range
   - **NEW in v2**: Each systematic symbol may be sent with multiple realizations

2. **Coded Phase**: Generate and send coded symbols until:
   - Total symbols sent reaches `K × R`
   - Or scheduler switches to different generation
   - **NEW in v2**: Each coded symbol may be sent with multiple realizations

### 8.4 Coded Symbol Generation

**Algorithm**:

```python
def generate_coded_symbol(generation_symbols, seed, degree):
    """
    generation_symbols: list of K source symbols
    seed: uint32 PRNG seed
    degree: number of symbols to XOR (typically 2-8)
    """
    rng = PRNG(seed)
    indices = rng.sample(range(len(generation_symbols)), degree)

    result = bytearray(symbol_size)
    for idx in indices:
        xor_into(result, generation_symbols[idx])

    return result, indices
```

**Degree Selection**:
- SHOULD use Robust Soliton distribution or similar
- Typical range: 2-8 for generation sizes 12-32
- Higher degrees provide better mixing but increase decode complexity

### 8.5 Realization Generation (NEW in v2)

**Algorithm**:

```python
def generate_realization(symbol_data, realization_id, mechanism):
    """
    symbol_data: original symbol bytes
    realization_id: 0 to D-1
    mechanism: diversity mechanism to apply
    """
    if mechanism == "mask_divergence":
        return apply_mask_divergence(symbol_data, realization_id)
    elif mechanism == "symbol_permutation":
        return apply_permutation(symbol_data, realization_id)
    elif mechanism == "payload_whitening":
        return apply_whitening(symbol_data, realization_id)
    elif mechanism == "spatial_permutation":
        return apply_spatial_permutation(symbol_data, realization_id)
    else:
        return symbol_data  # no diversity
```

**Mechanism Selection**:
- MAY use single mechanism or combination
- SHOULD be deterministic given realization_id
- MUST be reversible at receiver (or receiver-agnostic)

### 8.6 Broadcast Scheduler

**Active Generation Set**:

Maintain up to `G` active generations (default: 2)

**Airtime Allocation**:

For each frame to transmit:

1. Select generation `g` from active set with probability:
   ```
   P(g) ∝ β^(current_gen - g)
   ```
   where `β` is old/new ratio (default: 1.5)

2. If generation `g` has sent < `P` systematic symbols:
   - Select next systematic symbol
3. Else:
   - Generate coded symbol

4. **NEW in v2**: Select realization `r` for this transmission:
   - Round-robin: `r = transmission_count % D`
   - Or adaptive/ML-driven selection

5. Generate frame with selected (generation, symbol, realization)

**Generation Advancement**:

Advance to new generation when:
- Current generation has sent `K × R × D` total transmissions (with diversity)
- Or timeout threshold reached (optional)

### 8.7 Diversity Scheduling (NEW in v2)

**Question**: How to schedule realizations across transmissions?

**Strategy 1: Round-Robin** (recommended default)
```python
for each symbol transmission:
    realization_id = transmission_count % realization_count
```

**Strategy 2: Adaptive**
```python
# Track success rates per realization
success_rate[r] = successful_decodes[r] / total_transmissions[r]

# Prioritize realizations with lower success (need more coverage)
realization_id = argmin(success_rate)
```

**Strategy 3: ML-Driven** (future)
```python
# Policy network selects realization based on channel state
realization_id = policy_network.select(channel_state)
```

---

## 9. Receiver Algorithm

### 9.1 Frame Reception

**Per-Frame Processing**:

1. Capture frame from visual channel
2. Decode header
3. Validate `header_crc`
   - If invalid: discard frame, increment `bad_header_count`
4. Decode payload
5. Validate `payload_crc`
   - If invalid: treat as erasure, increment `bad_payload_count`
6. If both valid: route symbol to generation decoder

### 9.2 Realization Handling (NEW in v2)

**Key Principle**: Receiver accepts **first successful decode** of a logical symbol.

**Per-Symbol Processing**:

```python
def process_symbol(generation_id, symbol_index, realization_id, payload):
    """
    Process a successfully decoded symbol.
    """
    gen_state = get_generation_state(generation_id)

    # Check if we already have this logical symbol
    if symbol_index in gen_state.known_symbols:
        # Already have this symbol from a different realization
        # Ignore this duplicate
        gen_state.duplicate_count += 1
        return

    # New symbol, accept it
    gen_state.known_symbols.add(symbol_index)

    if symbol_type == SYSTEMATIC:
        gen_state.systematic_symbols[symbol_index] = payload
    else:  # CODED
        gen_state.coded_symbols.append(CodedSymbol(
            seed=coding_seed,
            degree=degree,
            indices=indices,
            payload=payload
        ))

    gen_state.last_progress_ts = current_time()

    # Check if decode should be attempted
    if should_attempt_decode(gen_state):
        attempt_decode(gen_state)
```

**Important**: Receiver does NOT need to track which realization succeeded, only that the logical symbol was recovered.

### 9.3 Generation State

For each generation `g`, receiver MUST maintain:

| State Field | Type | Description |
|-------------|------|-------------|
| `known_symbols` | set[int] | **NEW in v2**: Logical symbol indices (realization-agnostic) |
| `systematic_symbols` | dict[int, bytes] | Received systematic symbols |
| `coded_symbols` | list[CodedSymbol] | Received coded symbols with metadata |
| `decode_attempted` | bool | Whether decode has been tried |
| `decode_completed` | bool | Whether generation is fully recovered |
| `last_progress_ts` | timestamp | Last time new symbol was received |
| `duplicate_count` | int | **NEW in v2**: Count of duplicate realizations received |

**CodedSymbol Structure**:
```python
@dataclass
class CodedSymbol:
    seed: int
    degree: int
    indices: list[int]  # which source symbols were XORed
    payload: bytes
```

### 9.4 Decode Triggering

**Decode Condition**:

Attempt decode when:
```
len(known_symbols) >= K + M
```

where:
- `known_symbols` is the set of **unique logical symbols** (realization-agnostic)
- `M` is decode margin (default: 1)

**Important Change from v1**: Count **logical symbols**, not individual transmissions. Multiple realizations of the same symbol count as one.

**Decode Ordering** (SHOULD follow this priority):

1. **Direct Recovery**: If all `K` systematic symbols received, output immediately
2. **Lightweight Recovery**: Try peeling decoder or belief propagation
3. **Gaussian Elimination**: Fallback to full matrix solve if needed

**Important**: Receiver MUST NOT re-attempt decode on every new symbol. SHOULD only retry when:
- New symbols arrive after previous decode failure
- Sufficient additional symbols accumulated (e.g., +2 symbols)

### 9.5 Decode Algorithms

#### 9.5.1 Direct Recovery

**Condition**: All K systematic symbols received

```python
def direct_recovery(gen_state):
    if len(gen_state.systematic_symbols) == K:
        # All systematic symbols present
        return [gen_state.systematic_symbols[i] for i in range(K)]
    return None
```

**Complexity**: O(K)

#### 9.5.2 Peeling Decoder

**Concept**: Iteratively resolve coded symbols with degree 1

```python
def peeling_decoder(gen_state):
    unknown = set(range(K)) - set(gen_state.systematic_symbols.keys())
    resolved = dict(gen_state.systematic_symbols)

    while True:
        progress = False
        for coded in gen_state.coded_symbols:
            # Find coded symbols that XOR only unknown symbols
            unknown_in_coded = [i for i in coded.indices if i in unknown]

            if len(unknown_in_coded) == 1:
                # Can resolve this symbol
                idx = unknown_in_coded[0]
                resolved[idx] = xor_resolve(coded, resolved)
                unknown.remove(idx)
                progress = True

        if not progress:
            break

    if len(unknown) == 0:
        return [resolved[i] for i in range(K)]
    return None
```

**Complexity**: O(K × C) where C is number of coded symbols

#### 9.5.3 Gaussian Elimination

**Concept**: Solve linear system over GF(2)

```python
def gaussian_elimination(gen_state):
    # Build matrix: each row is a coded symbol equation
    # Augment with systematic symbols as trivial equations

    matrix = build_coding_matrix(gen_state)
    augmented = augment_with_payloads(matrix, gen_state)

    # Gaussian elimination over GF(2)
    rref = row_reduce_gf2(augmented)

    if is_full_rank(rref):
        return extract_solution(rref)
    return None
```

**Complexity**: O(K³) worst case

### 9.6 Symbol Output

When generation `g` is successfully decoded:

1. Mark `decode_completed = true`
2. Output `K` source symbols in order
3. Pass to reassembly layer
4. Optionally: free generation state to reclaim memory

### 9.7 Timeout and Cleanup

Receiver SHOULD implement timeout for stalled generations:

- If `current_time - last_progress_ts > timeout_threshold`:
  - Mark generation as failed
  - Report to upper layer
  - Free resources

**Recommended timeout**: 10-30 seconds depending on expected transmission rate

---

## 10. Three Core Trade-offs

### 10.1 Forward Progress

**Definition**: How quickly new data enters the transmission

**Controlled By**:
- `generation_overlap` (α): Higher overlap → slower progress
- `max_active_generations` (G): More active → slower per-generation progress
- `old_new_ratio` (β): Higher ratio → more time on old generations
- **NEW in v2**: `realization_count` (D): Higher D → slower progress (more airtime per symbol)

**Question Answered**: Does sender keep moving forward or get stuck revisiting old data?

### 10.2 Revisit Pressure

**Definition**: How quickly old generations receive additional recovery opportunities

**Controlled By**:
- `generation_overlap` (α): Higher overlap → more revisit paths
- `old_new_ratio` (β): Higher ratio → more frequent revisits
- `max_active_generations` (G): More active → distributed revisit opportunities
- **NEW in v2**: `realization_count` (D): Higher D → more recovery attempts per symbol

**Question Answered**: If a generation is almost complete, how long until it gets another useful symbol?

### 10.3 Recovery Robustness

**Definition**: Probability that a generation completes successfully under packet loss and decode failures

**Controlled By**:
- `generation_size` (K): Smaller → faster completion, less loss exposure
- `coded_redundancy` (R): Higher → more recovery capacity
- `systematic_prefix` (P): Higher → faster startup, better for sparse sampling
- `decode_margin` (M): Higher → more conservative decode triggering
- **NEW in v2**: `realization_count` (D): Higher D → better robustness against pattern-dependent failures

**Question Answered**: Will this generation complete or get stuck?

### 10.4 Parameter Interaction

These trade-offs are NOT independent:

- Increasing overlap improves revisit pressure BUT reduces forward progress
- Increasing redundancy improves robustness BUT reduces raw throughput
- Increasing active generations distributes revisit BUT slows per-generation completion
- **NEW in v2**: Increasing realization count improves robustness against pattern-dependent failures BUT reduces forward progress and increases airtime cost

**Key Insight**: There is no single "optimal" parameter set. Choice depends on:
- Sender FPS
- Capture FPS
- Packet loss rate
- Pattern-dependent failure rate (NEW in v2)
- Latency requirements

---

## 11. Operating Profiles

### 11.1 Profile Overview

OGRB defines three standard profiles optimized for different scenarios. Implementations SHOULD support all three profiles and allow users to select via configuration.

**NEW in v2**: Profiles now include `realization_count` parameter.

### 11.2 Profile 1: Robust

**Target Scenario**:
- Remote server transmission
- High packet loss (15-30%)
- Low sender FPS (5-10 fps)
- Recovery success rate is priority

**Parameter Configuration**:

```
symbol_size = 512 bytes
generation_size = 12~16 (recommended: 14)
generation_overlap = 0.25
systematic_prefix = 4
coded_redundancy = 1.4~1.6 (recommended: 1.5)
realization_count = 2~3 (recommended: 2)    # NEW in v2
max_active_generations = 2
old_new_ratio = 2.0~2.5 (recommended: 2.0)
decode_margin = 2
```

**Characteristics**:

- **Small generations**: Reduces time-to-completion, limits loss exposure
- **High coded redundancy**: Prioritizes recovery success over raw throughput
- **Strong old-generation bias**: Shortens tail latency for nearly-complete generations
- **Moderate overlap (25%)**: Provides secondary recovery path without excessive cost
- **NEW in v2**: **Light diversity (D=2)**: Mitigates pattern-dependent failures

**Typical Performance**:
- Generation size: ~7 KB
- Step size: ~5.25 KB
- Effective throughput: 50-65% of raw capacity (reduced due to diversity)
- Recovery success rate: >95% under 20% loss + pattern-dependent failures

**Design Rationale**:

This profile prioritizes "complete this generation quickly" over "push forward aggressively". The old/new ratio of 2.0 means sender spends twice as much airtime on older generations, ensuring they complete before moving on. Diversity (D=2) provides fallback for problematic visual patterns.

### 11.3 Profile 2: Balanced

**Target Scenario**:
- Local macOS screen capture
- Moderate packet loss (5-15%)
- Limited capture FPS (10-18 fps)
- Balance between throughput and robustness

**Parameter Configuration**:

```
symbol_size = 512 bytes
generation_size = 20~24 (recommended: 22)
generation_overlap = 0.125~0.25 (recommended: 0.125)
systematic_prefix = 6~8 (recommended: 6)
coded_redundancy = 1.15~1.25 (recommended: 1.2)
realization_count = 1~2 (recommended: 1)    # NEW in v2
max_active_generations = 2
old_new_ratio = 1.5
decode_margin = 1
```

**Characteristics**:

- **Medium generations**: Avoids frequent generation switching overhead
- **Low-to-medium overlap**: Maintains forward progress while providing limited revisit
- **Higher systematic prefix**: Better for receiver sparse sampling scenarios
- **Moderate redundancy**: Balances efficiency and recovery capability
- **NEW in v2**: **Minimal diversity (D=1)**: Prioritizes throughput, assumes clean channel

**Typical Performance**:
- Generation size: ~11 KB
- Step size: ~9.6 KB (at α=0.125)
- Effective throughput: 75-85% of raw capacity
- Recovery success rate: >90% under 10% loss

**Design Rationale**:

This profile is optimized for the common case where receiver does sparse sampling of sender's output stream. Higher systematic prefix ensures early symbols are more likely to be useful. Lower overlap (12.5%) prioritizes forward progress. Diversity disabled (D=1) for maximum throughput.

### 11.4 Profile 3: Throughput

**Target Scenario**:
- Ideal environment
- Very low packet loss (<5%)
- High sender and capture FPS (>20 fps)
- Maximum throughput is priority

**Parameter Configuration**:

```
symbol_size = 512 bytes
generation_size = 28~32 (recommended: 30)
generation_overlap = 0 (no overlap)
systematic_prefix = 8~12 (recommended: 10)
coded_redundancy = 1.05~1.10 (recommended: 1.08)
realization_count = 1 (diversity disabled)  # NEW in v2
max_active_generations = 1
old_new_ratio = 1.0 (no bias)
decode_margin = 0
```

**Characteristics**:

- **Large generations**: Maximizes net efficiency, reduces switching overhead
- **Zero overlap**: Maximum forward progress speed
- **Minimal redundancy**: Only essential protection
- **Single active generation**: No airtime fragmentation
- **NEW in v2**: **No diversity (D=1)**: Maximum throughput, assumes clean channel

**Typical Performance**:
- Generation size: ~15 KB
- Step size: ~15 KB (no overlap)
- Effective throughput: 90-95% of raw capacity
- Recovery success rate: >85% under 5% loss

**Design Rationale**:

This profile sacrifices worst-case recovery experience for maximum raw throughput. It assumes the channel is clean enough that aggressive parameters won't cause frequent generation failures. No diversity overhead.

### 11.5 Profile Selection Guidelines

| Scenario | Sender FPS | Loss Rate | Pattern Failures | Capture FPS | Recommended Profile |
|----------|-----------|-----------|------------------|-------------|---------------------|
| Remote server | 5-10 | 15-30% | High | 10-15 | **Robust** (D=2) |
| Local macOS | 15-25 | 5-15% | Low | 10-18 | **Balanced** (D=1) |
| Ideal lab | >25 | <5% | None | >20 | **Throughput** (D=1) |
| Unknown | Any | Unknown | Unknown | Any | **Balanced** (safe default) |

**NEW in v2**: Pattern failure rate is now a consideration for profile selection.

### 11.6 Profile Customization

Users MAY override individual parameters while using a profile as baseline:

```bash
# Start from balanced, but increase redundancy
--ogrb-profile balanced --ogrb-coded-redundancy 1.4

# Start from balanced, enable diversity
--ogrb-profile balanced --ogrb-realization-count 2
```

Implementations SHOULD validate that customized parameters remain internally consistent.

---

## 12. Key Design Decisions

### 12.1 Overlap is an Expensive Knob

**Principle**: Overlap SHOULD NOT be the first parameter to increase in high-loss scenarios.

**Rationale**:
- Overlap directly reduces forward progress speed
- Overlap increases airtime duplication cost
- Other parameters (smaller generations, higher redundancy, stronger old-generation bias) often provide better loss tolerance per unit cost

**Recommended Priority** (high loss scenarios):
1. Reduce `generation_size`
2. Increase `coded_redundancy`
3. Increase `old_new_ratio` (bias toward old generations)
4. **NEW in v2**: Increase `realization_count` (if pattern-dependent failures observed)
5. Only then consider increasing `overlap`

**Example**:

Instead of:
```
generation_size = 24, overlap = 0.5, redundancy = 1.2, realization_count = 1
```

Prefer:
```
generation_size = 16, overlap = 0.25, redundancy = 1.5, realization_count = 2
```

### 12.2 Max Active Generations Default

**Principle**: `max_active_generations = 2` SHOULD be the default.

**Rationale**:
- `G = 1`: Too aggressive, no revisit opportunity for stalled generations
- `G = 2`: Balanced, allows one old generation to receive revisits while pushing forward
- `G = 3`: Fragments airtime excessively, especially at low sender FPS

**When to Use G=1**:
- Ideal environment with very low loss
- Throughput is absolute priority
- Willing to accept occasional generation failures

**When to Use G=3**:
- Experimental scenarios only
- NOT recommended as default robust configuration

### 12.3 Systematic Prefix Strategy

**Principle**: Higher systematic prefix is better for sparse sampling scenarios.

**Rationale**:

In local screen capture, receiver often samples sender's output stream sparsely (e.g., 12 fps capture vs 25 fps sender). Early systematic symbols have higher probability of being captured.

**Recommended Values**:
- Robust profile: 4 (lower, because redundancy is high anyway)
- Balanced profile: 6-8 (higher, optimized for sparse sampling)
- Throughput profile: 8-12 (highest, minimal coded overhead)

### 12.4 Realization Count Strategy (NEW in v2)

**Principle**: Enable diversity (D>1) only when pattern-dependent failures are observed.

**Rationale**:
- Diversity increases airtime cost proportionally (D=2 → 2× transmissions per symbol)
- Diversity is most effective when failures are pattern-dependent, not random
- Clean channels with random loss benefit more from redundancy than diversity

**Recommended Values**:
- D=1: Default for clean channels (local capture, low compression)
- D=2: Moderate pattern-dependent failures (remote desktop, H.264 compression)
- D=3: High pattern-dependent failures (aggressive compression, poor capture quality)

**Diagnostic**: If increasing redundancy doesn't improve success rate, try increasing diversity instead.

### 12.5 No Sender-Side Adaptation

**Principle**: First version MUST use static profiles, NOT sender-side adaptation.

**Rationale**:
- Visual broadcast channel typically lacks reliable feedback path
- Sender cannot reliably know:
  - Actual packet loss rate
  - Receiver decode progress
  - Generation completion status
  - Pattern-dependent failure rate (NEW in v2)
- Static profiles with offline benchmarking are more predictable

**Future Extension**:

Sender-side adaptation MAY be added later if:
- Reliable reverse control channel is established
- Receiver can report generation completion status
- Adaptation logic is thoroughly benchmarked
- **NEW in v2**: Policy layer (Layer 4) provides ML-driven adaptation

---

## 13. ML Integration (NEW in v2)

### 13.1 ML-Assisted Decoding

Machine learning may improve perception components at the **physical frame layer**.

**Examples**:
- Symbol classifier (improve decode accuracy)
- Header classifier (improve header extraction)
- Confidence estimator (predict decode success probability)
- Pattern quality estimator (detect problematic visual patterns)

**Important**: These operate **below the protocol layer** and do not change protocol semantics.

**Integration Point**:
```
Physical Frame Layer (Layer 0)
  ├─ Traditional decoder (baseline)
  └─ ML-assisted decoder (optional enhancement)
```

### 13.2 ML-Driven Protocol Control

Future systems may use ML to control protocol decisions via the **policy layer**.

**Possible parameters controlled by policy**:
- Mask selection
- Realization scheduling
- Redundancy strength (dynamic R adjustment)
- Generation scheduling (dynamic β adjustment)
- Diversity mechanism selection

**Architecture**:
```
Policy Layer (Layer 4)
  ├─ Static heuristics (baseline)
  ├─ Adaptive algorithms (rule-based)
  └─ ML policy networks (future)
```

**Example Policy Network**:
```python
class OGRBPolicy:
    def select_realization(self, channel_state, symbol_history):
        """
        Select realization based on channel state.
        """
        features = extract_features(channel_state, symbol_history)
        realization_id = self.policy_net(features)
        return realization_id

    def adjust_redundancy(self, generation_state):
        """
        Dynamically adjust redundancy based on generation progress.
        """
        features = extract_generation_features(generation_state)
        redundancy_adjustment = self.redundancy_net(features)
        return redundancy_adjustment
```

### 13.3 ML Training Data

**Potential training signals**:
- Decode success/failure per realization
- Generation completion latency
- Symbol-level decode confidence
- Channel quality metrics (blur, compression artifacts)

**Training objective**:
- Maximize goodput
- Minimize generation completion latency
- Maximize generation success rate

### 13.4 ML Deployment Considerations

**Requirements for ML components**:
1. MUST NOT violate protocol invariants
2. MUST degrade gracefully to baseline when ML unavailable
3. SHOULD be independently testable
4. SHOULD provide interpretable decisions (for debugging)

**Baseline requirement**: Protocol MUST work without ML components.

---

## 14. Performance Metrics

### 14.1 Required Metrics

Implementations MUST track and report:

**Sender Metrics**:
- `frames_sent`: Total frames transmitted
- `systematic_sent`: Count of systematic symbols sent
- `coded_sent`: Count of coded symbols sent
- `generations_started`: Number of generations entered
- `generations_completed`: Number of generations fully transmitted
- **NEW in v2**: `realizations_sent[r]`: Count per realization (r = 0 to D-1)

**Receiver Metrics**:
- `frames_received`: Total frames captured
- `bad_header_count`: Frames with invalid header CRC
- `bad_payload_count`: Frames with invalid payload CRC
- `good_frames`: Frames with both header and payload valid
- `generations_decoded`: Number of generations successfully recovered
- `generations_failed`: Number of generations that timed out
- **NEW in v2**: `duplicate_symbols`: Count of duplicate realizations received
- **NEW in v2**: `realizations_decoded[r]`: Count per realization (r = 0 to D-1)

### 14.2 Derived Metrics

**Frame Success Rate**:
```
frame_success_rate = good_frames / frames_received
```

**Generation Success Rate**:
```
generation_success_rate = generations_decoded / generations_started
```

**Raw Throughput** (sender perspective):
```
raw_throughput = (frames_sent × symbol_size) / elapsed_time
```

**Goodput** (receiver perspective):
```
goodput = (generations_decoded × generation_size × symbol_size) / elapsed_time
```

**Effective Efficiency**:
```
efficiency = goodput / raw_throughput
```

**NEW in v2: Diversity Efficiency**:
```
diversity_efficiency = unique_symbols_decoded / total_symbols_received
```

**NEW in v2: Realization Success Rate**:
```
realization_success_rate[r] = realizations_decoded[r] / realizations_sent[r]
```

### 14.3 Benchmark Requirements

When benchmarking OGRB implementations, reports SHOULD include:

1. **Environment Description**:
   - Sender FPS
   - Capture FPS
   - Simulated or measured loss rate
   - **NEW in v2**: Pattern-dependent failure characteristics
   - Test duration

2. **Configuration**:
   - Profile used (or custom parameters)
   - All parameter values
   - **NEW in v2**: Realization count and diversity mechanism

3. **Results**:
   - All required metrics (Section 14.1)
   - All derived metrics (Section 14.2)
   - Latency distribution (time from generation start to completion)
   - **NEW in v2**: Per-realization success rates

---

## 15. Implementation Requirements

### 15.1 Mandatory Requirements (MUST)

Implementations MUST satisfy the following:

1. **Layer Separation**:
   - Physical frame layer, realization layer, generation coding layer, broadcast scheduling layer, and policy layer MUST be independently testable
   - No cross-layer coupling beyond defined interfaces

2. **Header Validation**:
   - Header CRC MUST be validated before payload decode
   - Invalid headers MUST be discarded immediately

3. **Generation State Tracking**:
   - Receiver MUST maintain state for each active generation
   - State MUST include at minimum: known logical symbols (realization-agnostic), systematic symbols, coded symbols, decode status, last progress timestamp

4. **Realization Deduplication** (NEW in v2):
   - Receiver MUST deduplicate symbols across realizations
   - Only first successful decode of a logical symbol MUST be accepted

5. **Profile Support**:
   - MUST support at least the "balanced" profile
   - SHOULD support all three standard profiles (robust, balanced, throughput)

6. **Metrics Reporting**:
   - MUST track all required metrics (Section 14.1)
   - MUST provide mechanism to export metrics for analysis

### 15.2 Recommended Requirements (SHOULD)

Implementations SHOULD satisfy the following:

1. **Decode Efficiency**:
   - SHOULD attempt lightweight recovery (peeling/BP) before Gaussian elimination
   - SHOULD NOT retry decode on every new symbol arrival

2. **Memory Management**:
   - SHOULD free generation state after successful decode
   - SHOULD implement timeout for stalled generations

3. **Parameter Validation**:
   - SHOULD validate parameter consistency at initialization
   - SHOULD warn if custom parameters deviate significantly from profile recommendations

4. **Progress Reporting**:
   - SHOULD provide real-time progress indicators
   - SHOULD report generation completion events

5. **Realization Diversity** (NEW in v2):
   - SHOULD support at least one diversity mechanism (mask divergence recommended)
   - SHOULD allow diversity to be disabled (D=1) for maximum throughput

### 15.3 Prohibited Behaviors (MUST NOT)

Implementations MUST NOT:

1. **Sender-Side Adaptation**:
   - MUST NOT implement sender-side adaptation in first version (without policy layer)
   - MUST NOT assume reliable feedback channel exists

2. **Cross-Generation Recovery**:
   - Physical frame layer MUST NOT perform cross-generation recovery
   - Generation coding layer MUST NOT depend on specific frame arrival order

3. **Implicit Assumptions**:
   - MUST NOT assume all frames will be received
   - MUST NOT assume epoch boundaries are visible
   - MUST NOT assume sender and receiver clocks are synchronized
   - **NEW in v2**: MUST NOT assume all realizations have equal success rates

4. **Realization Coupling** (NEW in v2):
   - Realization layer MUST NOT make scheduling decisions
   - Generation coding layer MUST NOT depend on specific realization success

---

## 16. CLI Interface

### 16.1 Sender CLI

**Profile-Based Configuration** (recommended):

```bash
screen-airdrop-sender \
  --protocol ogrb \
  --ogrb-profile balanced \
  --input ./file.tar.gz \
  --window-name "screen-airdrop"
```

**Advanced Parameter Override**:

```bash
screen-airdrop-sender \
  --protocol ogrb \
  --ogrb-profile balanced \
  --ogrb-generation-size 24 \
  --ogrb-coded-redundancy 1.3 \
  --ogrb-realization-count 2 \
  --input ./file.tar.gz
```

**Full Manual Configuration**:

```bash
screen-airdrop-sender \
  --protocol ogrb \
  --ogrb-symbol-size 512 \
  --ogrb-generation-size 22 \
  --ogrb-generation-overlap 0.125 \
  --ogrb-systematic-prefix 6 \
  --ogrb-coded-redundancy 1.2 \
  --ogrb-realization-count 1 \
  --ogrb-max-active-generations 2 \
  --ogrb-old-new-ratio 1.5 \
  --input ./file.tar.gz
```

### 16.2 Receiver CLI

**Basic Usage**:

```bash
screen-airdrop-receiver \
  --protocol ogrb \
  --source screen \
  --window-title "Remote Desktop" \
  --output-dir ./recovered
```

**With Decode Margin Override**:

```bash
screen-airdrop-receiver \
  --protocol ogrb \
  --ogrb-decode-margin 2 \
  --source screen \
  --output-dir ./recovered
```

### 16.3 Parameter Naming Convention

All OGRB-specific parameters SHOULD use the `--ogrb-` prefix to avoid namespace collision with other protocols.

**Standard Parameter Names**:
- `--ogrb-profile`: Profile selection (robust/balanced/throughput)
- `--ogrb-symbol-size`: Symbol size in bytes
- `--ogrb-generation-size`: Number of symbols per generation
- `--ogrb-generation-overlap`: Overlap fraction (0.0-0.5)
- `--ogrb-systematic-prefix`: Number of systematic symbols sent first
- `--ogrb-coded-redundancy`: Total symbols / generation size ratio
- **`--ogrb-realization-count`**: **NEW in v2**: Number of visual realizations per symbol
- `--ogrb-max-active-generations`: Maximum concurrent active generations
- `--ogrb-old-new-ratio`: Airtime bias toward older generations
- `--ogrb-decode-margin`: Extra symbols required before decode attempt

---

## 17. Testing Requirements

### 17.1 Unit Tests

Implementations MUST include unit tests for:

1. **Generation Partitioning**:
   - Verify correct symbol ranges for each generation
   - Test overlap calculation
   - Test step size computation

2. **Coded Symbol Generation**:
   - Verify deterministic generation from seed
   - Test degree distribution
   - Verify XOR correctness

3. **Realization Generation** (NEW in v2):
   - Test each diversity mechanism independently
   - Verify deterministic generation from realization_id
   - Test reversibility (where applicable)

4. **Header Encoding/Decoding**:
   - Test all header fields including realization_id
   - Verify CRC calculation
   - Test invalid header rejection

5. **Decode Logic**:
   - Test direct recovery (all systematic received)
   - Test peeling decoder
   - Test Gaussian elimination fallback
   - **NEW in v2**: Test realization deduplication

### 17.2 Integration Tests

Implementations SHOULD include integration tests for:

1. **Synthetic Roundtrip**:
   - Generate test data
   - Encode with OGRB sender
   - Decode with OGRB receiver (no loss)
   - Verify bit-exact recovery
   - **NEW in v2**: Test with diversity enabled (D>1)

2. **Lossy Channel Simulation**:
   - Simulate packet loss at various rates (5%, 10%, 20%)
   - Verify generation recovery success rate
   - Measure goodput vs raw throughput
   - **NEW in v2**: Test with pattern-dependent failures

3. **Realization Diversity Tests** (NEW in v2):
   - Test that different realizations of same symbol are deduplicated
   - Verify that any single realization success is sufficient
   - Measure diversity efficiency

4. **Profile Validation**:
   - Test all three standard profiles
   - Verify parameter consistency
   - Measure performance characteristics

### 17.3 Benchmark Tests

Implementations SHOULD support benchmark modes:

1. **Replay Benchmark**:
   - Use pre-captured frame sequences
   - Measure decode performance
   - Compare across profiles
   - **NEW in v2**: Compare across diversity settings

2. **End-to-End Benchmark**:
   - Real screen capture
   - Measure actual throughput
   - Track generation completion latency
   - **NEW in v2**: Track per-realization success rates

3. **Diversity Effectiveness Benchmark** (NEW in v2):
   - Measure improvement from diversity (D=1 vs D=2 vs D=3)
   - Identify pattern-dependent failure scenarios
   - Quantify diversity overhead vs benefit

---

## 18. Examples

### 18.1 Example: Balanced Profile Calculation

**Configuration**:
```
symbol_size = 512 bytes
generation_size = 22
generation_overlap = 0.125
systematic_prefix = 6
coded_redundancy = 1.2
realization_count = 1        # NEW in v2
```

**Derived Values**:
```
step_size = 22 × (1 - 0.125) = 19.25 symbols
generation_data_size = 22 × 512 = 11,264 bytes ≈ 11 KB
step_data_size = 19.25 × 512 = 9,856 bytes ≈ 9.6 KB
total_symbols_per_gen = 22 × 1.2 = 26.4 symbols
coded_symbols_per_gen = 26.4 - 6 = 20.4 symbols
effective_transmissions = 26.4 × 1 = 26.4 frames    # NEW in v2
```

**Generation Boundaries** (first 3 generations):
```
Generation 0: symbols [0, 21]     (22 symbols)
Generation 1: symbols [19, 40]    (22 symbols, overlap with gen 0: [19, 21])
Generation 2: symbols [38, 59]    (22 symbols, overlap with gen 1: [38, 40])
```

### 18.2 Example: Robust Profile with Diversity (NEW in v2)

**Configuration**:
```
symbol_size = 512 bytes
generation_size = 14
generation_overlap = 0.25
systematic_prefix = 4
coded_redundancy = 1.5
realization_count = 2        # NEW in v2
```

**Derived Values**:
```
step_size = 14 × (1 - 0.25) = 10.5 symbols
generation_data_size = 14 × 512 = 7,168 bytes ≈ 7 KB
step_data_size = 10.5 × 512 = 5,376 bytes ≈ 5.25 KB
total_symbols_per_gen = 14 × 1.5 = 21 symbols
coded_symbols_per_gen = 21 - 4 = 17 symbols
effective_transmissions = 21 × 2 = 42 frames    # NEW in v2: doubled due to diversity
```

**Airtime Cost Analysis**:
- Without diversity (D=1): 21 frames per generation
- With diversity (D=2): 42 frames per generation
- Overhead: 2× airtime cost
- Benefit: Improved robustness against pattern-dependent failures

### 18.3 Example: Transmission Sequence

**Scenario**: Send 100 KB file with balanced profile

**Steps**:

1. **Partition**: 100 KB ÷ 512 bytes = 196 symbols total

2. **Generation Count**:
   - Step size = 19.25 symbols
   - Generations needed ≈ 196 ÷ 19.25 ≈ 10.2 → 11 generations

3. **Transmission**:
   - Generation 0: Send symbols [0, 21]
     - First 6 systematic: [0, 1, 2, 3, 4, 5]
     - Then ~20 coded symbols
   - Generation 1: Send symbols [19, 40]
     - First 6 systematic: [19, 20, 21, 22, 23, 24]
     - Then ~20 coded symbols
   - Continue...

4. **Scheduler Behavior** (with max_active_generations=2, old_new_ratio=1.5):
   - When gen 0 and gen 1 are active:
     - P(select gen 0) ∝ 1.5^1 = 1.5
     - P(select gen 1) ∝ 1.5^0 = 1.0
     - Gen 0 gets 60% airtime, gen 1 gets 40%

### 18.4 Example: Transmission Sequence with Diversity (NEW in v2)

**Scenario**: Send with robust profile (D=2)

**Transmission order for generation 0, symbol 0**:
```
Frame 1: gen=0, symbol=0, type=SYSTEMATIC, realization=0
Frame 2: gen=0, symbol=1, type=SYSTEMATIC, realization=0
...
Frame N: gen=0, symbol=0, type=SYSTEMATIC, realization=1  # Second realization
```

**Receiver behavior**:
```
Receive Frame 1: symbol 0, realization 0 → decode success → accept
Receive Frame N: symbol 0, realization 1 → already have symbol 0 → ignore
```

### 18.5 Example: Receiver Decode Scenario

**Scenario**: Receiver with 10% packet loss

**Generation 0 Reception**:
```
Expected: 26 symbols (6 systematic + 20 coded)
Received: 24 symbols (5 systematic + 19 coded)
Loss: 2 symbols

Decode condition: 24 >= 22 + 1 (K + M) ✓
Attempt decode: Success (24 symbols sufficient for K=22)
```

**Generation 1 Reception**:
```
Expected: 26 symbols
Received: 21 symbols (4 systematic + 17 coded)
Loss: 5 symbols

Decode condition: 21 >= 22 + 1 ✗
Wait for more symbols...

After 3 more symbols arrive:
Received: 24 symbols total
Decode condition: 24 >= 23 ✓
Attempt decode: Success
```

### 18.6 Example: Receiver with Diversity (NEW in v2)

**Scenario**: Receiver with 10% packet loss + pattern-dependent failures (D=2)

**Generation 0 Reception**:
```
Expected: 42 transmissions (21 symbols × 2 realizations)
Received: 38 transmissions
  - Symbol 0: realization 0 failed, realization 1 success → accept
  - Symbol 1: realization 0 success → accept (ignore realization 1 later)
  - Symbol 2: both realizations failed → erasure
  - ...
Unique symbols decoded: 20

Decode condition: 20 >= 22 + 1 ✗
Wait for more symbols...

After overlap with generation 1:
Symbols [19, 21] recovered from generation 1
Total unique symbols: 22
Decode condition: 22 >= 23 ✗ (still need 1 more)

After 2 more transmissions:
Total unique symbols: 23
Decode condition: 23 >= 23 ✓
Attempt decode: Success
```

**Analysis**:
- Without diversity: Would need all 26 transmissions to succeed
- With diversity: Pattern-dependent failures mitigated by alternative realizations
- Trade-off: 2× airtime cost, but higher success rate

---

## 19. Comparison with Alternatives

### 19.1 vs Sequential Transmission

**Sequential** (current basic/compact):
- Each frame = complete packet
- Lost frame = wait for next epoch
- Heavy frame-internal ECC

**OGRB**:
- Each frame = one symbol
- Lost frame = erasure, recoverable via coding
- Lightweight frame validation, heavy cross-frame coding
- **NEW in v2**: Multiple realizations per symbol for pattern robustness

**Advantage**: OGRB provides better loss tolerance and eliminates epoch waiting. v2 adds robustness against pattern-dependent failures.

### 19.2 vs Whole-File Fountain

**Whole-File Fountain**:
- Entire file as one generation
- Maximum flexibility
- High decode complexity
- Long time-to-first-recovery

**OGRB**:
- Small generations (10-30 symbols)
- Limited flexibility
- Low decode complexity
- Fast per-generation recovery
- **NEW in v2**: Realization diversity for visual channel robustness

**Advantage**: OGRB provides predictable latency and manageable complexity, with v2 adding visual channel-specific optimizations.

### 19.3 vs Fixed-Rate Block Codes

**Fixed-Rate Block Codes** (e.g., Reed-Solomon):
- Fixed redundancy ratio
- Optimal for known loss rate
- Cannot adapt to varying conditions

**OGRB**:
- Rateless coding (can generate unlimited coded symbols)
- Works across varying loss rates
- Sender can continue transmitting until receiver signals completion
- **NEW in v2**: Realization diversity adapts to pattern-dependent failures

**Advantage**: OGRB handles unknown or varying loss rates gracefully. v2 handles pattern-dependent failures that fixed-rate codes cannot address.

### 19.4 OGRB v1 vs v2

**v1**:
- Single visual representation per symbol
- Four-layer architecture
- Static profiles only
- Optimized for random packet loss

**v2**:
- Multiple visual realizations per symbol
- Five-layer architecture (adds realization layer and policy layer)
- Optional ML-driven adaptation
- Optimized for both random loss and pattern-dependent failures

**When to use v1**: Clean channels with random loss only
**When to use v2**: Channels with compression, blur, or pattern-dependent failures

---

## 20. Integration with Other Protocols

### 20.1 Coexistence with Other Payload Types

OGRB frames may coexist with other payload types in a hybrid system.

**Possible payload types**:
```
SYMBOL_PAYLOAD    (OGRB)
TILE_UPDATE       (spatial update)
KEYFRAME          (full frame refresh)
```

OGRB applies only to `SYMBOL_PAYLOAD` frames.

### 20.2 Integration with Physical Layer Protocols

OGRB is agnostic to the physical layer encoding.

**Compatible physical layers**:
- Basic protocol (SAR3, four-corner fixed-grid)
- Compact protocol (higher density)
- Gray4 protocol (NEW, 4-level grayscale)
- Future layered protocols

**Realization diversity** (v2) can be implemented at:
- Physical layer (different masks, spatial layouts)
- Data layer (permutation, whitening)
- Or both

---

## 21. Future Extensions

### 21.1 Potential Enhancements

The following features are NOT part of the initial specification but MAY be added in future versions:

1. **Sender-Side Adaptation**:
   - Dynamic profile switching based on feedback
   - Requires reliable reverse control channel
   - Should be thoroughly benchmarked before deployment
   - **v2 enables this via policy layer**

2. **Unequal Error Protection**:
   - Different protection levels for different data regions
   - Higher redundancy for critical metadata
   - Lower redundancy for bulk data

3. **Multi-Layer Coding**:
   - Combine OGRB with physical layer improvements (gray4, layered)
   - Optimize control plane vs data plane separately

4. **Progressive Decode**:
   - Partial generation output before full recovery
   - Useful for streaming scenarios
   - Requires careful handling of incomplete data

5. **Cross-Generation Coding**:
   - Limited coding across generation boundaries
   - Provides additional recovery paths
   - Must maintain decode complexity bounds

6. **Advanced Diversity Mechanisms** (v2):
   - ML-selected realizations
   - Adaptive modulation per realization
   - Context-aware diversity policies

7. **Reinforcement Learning Policy** (v2):
   - Train policy network to optimize scheduling
   - Learn from channel feedback
   - Adapt to user-specific environments

### 21.2 Non-Goals

The following are explicitly NOT goals for OGRB:

1. **Real-Time Streaming**: OGRB is optimized for file transfer, not low-latency streaming
2. **Bidirectional Communication**: No built-in ACK/NACK mechanism
3. **Encryption**: Security should be handled at application layer
4. **Compression**: Data should be compressed before OGRB encoding

---

## 22. Security Considerations

OGRB does not provide:

```
encryption
authentication
compression
```

These functions must be implemented above the protocol layer.

**Recommendations**:
- Encrypt data before OGRB encoding
- Use authenticated encryption (e.g., AES-GCM)
- Compress data before encryption
- Verify file integrity after reassembly (SHA-256)

---

## 23. Glossary

**Airtime**: The transmission time allocated to a particular generation or symbol type.

**Coded Symbol**: A linear combination (XOR) of multiple source symbols within a generation.

**Decode Margin**: Extra symbols required beyond the minimum (K) before attempting decode.

**Degree**: Number of source symbols XORed together to create a coded symbol.

**Diversity Efficiency** (NEW in v2): Ratio of unique symbols decoded to total symbols received.

**Erasure**: A lost or corrupted frame treated as missing data (position known, value unknown).

**Generation**: A group of consecutive source symbols that can be independently recovered.

**Goodput**: Effective data throughput measured as successfully recovered data per unit time.

**Logical Symbol** (NEW in v2): A source symbol in generation context, may have multiple realizations.

**Overlap**: Fraction of symbols shared between consecutive generations.

**Pattern-Dependent Failure** (NEW in v2): Decode failure caused by visual pattern interaction with channel impairments.

**Peeling Decoder**: Lightweight iterative decoder that resolves symbols one at a time.

**Policy Layer** (NEW in v2): Optional layer for ML-driven adaptive control.

**Profile**: A named set of parameter values optimized for a specific scenario.

**Rateless Code**: A code that can generate unlimited coded symbols from a fixed set of source symbols.

**Realization** (NEW in v2): A specific visual representation of a logical symbol.

**Realization Diversity** (NEW in v2): Multiple visual representations per logical symbol.

**Revisit Pressure**: How frequently old generations receive additional recovery opportunities.

**Source Symbol**: A fixed-size unit of original data (default: 512 bytes).

**Step Size**: Number of symbols advanced between consecutive generation starts.

**Systematic Symbol**: A source symbol transmitted without encoding (direct copy).

---

## 24. References

### 24.1 Related Protocols

- **LT Codes**: Luby Transform codes, foundation for rateless coding
- **Raptor Codes**: Systematic rateless codes with pre-coding
- **RaptorQ**: IETF RFC 6330, standardized fountain code

### 24.2 Relevant Literature

- Luby, M. (2002). "LT codes". *Proceedings of the 43rd Annual IEEE Symposium on Foundations of Computer Science*.
- Shokrollahi, A. (2006). "Raptor codes". *IEEE Transactions on Information Theory*.
- MacKay, D. J. C. (2005). "Fountain codes". *IEE Proceedings - Communications*.

### 24.3 Screen-Airdrop Documentation

- [throughput_optimization_plan.md](./throughput_optimization_plan.md): Overall optimization strategy
- [protocol_efficiency_report.md](./protocol_efficiency_report.md): Single-frame efficiency analysis
- [benchmark_status.md](./benchmark_status.md): Current benchmark results
- [screen_airdrop_robustness_plan_v_1.md](./screen_airdrop_robustness_plan_v_1.md): Robustness improvement plan
- [header_ecc_experiment_plan.md](./header_ecc_experiment_plan.md): Header ECC experiments

---

## 25. Revision History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-03-09 | Initial specification |
| 2.0 | 2026-03-15 | Added realization diversity, policy layer, ML integration |

---

## Appendix A: Parameter Quick Reference

### A.1 Robust Profile

```
symbol_size = 512
generation_size = 14
generation_overlap = 0.25
systematic_prefix = 4
coded_redundancy = 1.5
realization_count = 2          # NEW in v2
max_active_generations = 2
old_new_ratio = 2.0
decode_margin = 2

# Derived
step_size = 10.5 symbols ≈ 5.25 KB
generation_data_size = 7 KB
total_symbols_per_gen = 21
coded_symbols_per_gen = 17
effective_transmissions = 42   # NEW in v2: 21 × 2
```

### A.2 Balanced Profile

```
symbol_size = 512
generation_size = 22
generation_overlap = 0.125
systematic_prefix = 6
coded_redundancy = 1.2
realization_count = 1          # NEW in v2
max_active_generations = 2
old_new_ratio = 1.5
decode_margin = 1

# Derived
step_size = 19.25 symbols ≈ 9.6 KB
generation_data_size = 11 KB
total_symbols_per_gen = 26.4
coded_symbols_per_gen = 20.4
effective_transmissions = 26.4 # NEW in v2: 26.4 × 1
```

### A.3 Throughput Profile

```
symbol_size = 512
generation_size = 30
generation_overlap = 0
systematic_prefix = 10
coded_redundancy = 1.08
realization_count = 1          # NEW in v2
max_active_generations = 1
old_new_ratio = 1.0
decode_margin = 0

# Derived
step_size = 30 symbols = 15 KB
generation_data_size = 15 KB
total_symbols_per_gen = 32.4
coded_symbols_per_gen = 22.4
effective_transmissions = 32.4 # NEW in v2: 32.4 × 1
```

---

## Appendix B: Implementation Checklist

### B.1 Sender Implementation

- [ ] Generation partitioning with overlap
- [ ] Systematic symbol transmission
- [ ] Coded symbol generation (with PRNG seed)
- [ ] Degree distribution (Robust Soliton or similar)
- [ ] **NEW in v2**: Realization generation (at least one diversity mechanism)
- [ ] **NEW in v2**: Realization scheduling (round-robin minimum)
- [ ] Broadcast scheduler with airtime allocation
- [ ] Active generation set management
- [ ] Header encoding with CRC (including realization_id)
- [ ] Payload CRC calculation
- [ ] Metrics tracking (frames sent, generations started, etc.)
- [ ] **NEW in v2**: Per-realization metrics tracking
- [ ] Profile support (at least balanced)
- [ ] CLI parameter parsing

### B.2 Receiver Implementation

- [ ] Frame capture and decode
- [ ] Header CRC validation
- [ ] Payload CRC validation
- [ ] **NEW in v2**: Realization deduplication (logical symbol tracking)
- [ ] Generation state management
- [ ] Systematic symbol storage
- [ ] Coded symbol storage with metadata
- [ ] Decode triggering logic
- [ ] Direct recovery (all systematic received)
- [ ] Peeling decoder
- [ ] Gaussian elimination fallback
- [ ] Generation timeout and cleanup
- [ ] Metrics tracking (frames received, generations decoded, etc.)
- [ ] **NEW in v2**: Duplicate symbol counting
- [ ] **NEW in v2**: Per-realization success rate tracking
- [ ] Profile support
- [ ] CLI parameter parsing

### B.3 Testing

- [ ] Unit tests for generation partitioning
- [ ] Unit tests for coded symbol generation
- [ ] **NEW in v2**: Unit tests for realization generation
- [ ] **NEW in v2**: Unit tests for realization deduplication
- [ ] Unit tests for header encoding/decoding
- [ ] Unit tests for decode logic
- [ ] Integration test: synthetic roundtrip (no loss)
- [ ] Integration test: lossy channel simulation (5%, 10%, 20%)
- [ ] **NEW in v2**: Integration test: pattern-dependent failure simulation
- [ ] **NEW in v2**: Integration test: diversity effectiveness (D=1 vs D=2)
- [ ] Integration test: all three profiles
- [ ] Benchmark: replay mode
- [ ] Benchmark: end-to-end with real screen capture
- [ ] **NEW in v2**: Benchmark: diversity overhead measurement

---

## Appendix C: Troubleshooting Guide

### C.1 Low Goodput

**Symptoms**: Effective throughput much lower than expected

**Possible Causes**:
1. Packet loss rate higher than profile designed for
   - **Solution**: Switch to more robust profile or increase redundancy
2. Capture FPS too low
   - **Solution**: Optimize capture backend or reduce sender FPS
3. Decode failures due to insufficient symbols
   - **Solution**: Increase decode margin or coded redundancy
4. **NEW in v2**: Pattern-dependent failures
   - **Solution**: Enable diversity (increase realization_count)

### C.2 High Generation Failure Rate

**Symptoms**: Many generations timeout without completing

**Possible Causes**:
1. Generation size too large for loss rate
   - **Solution**: Reduce generation size
2. Coded redundancy insufficient
   - **Solution**: Increase coded redundancy
3. Max active generations too high, fragmenting airtime
   - **Solution**: Reduce to 2 or 1
4. **NEW in v2**: High pattern-dependent failure rate
   - **Solution**: Enable diversity (D=2 or D=3)

### C.3 Slow Forward Progress

**Symptoms**: Sender keeps revisiting old generations, new data not advancing

**Possible Causes**:
1. Overlap too high
   - **Solution**: Reduce overlap (try 0.125 instead of 0.25)
2. Old/new ratio too high
   - **Solution**: Reduce old/new ratio (try 1.5 instead of 2.0)
3. Too many active generations
   - **Solution**: Reduce max active generations
4. **NEW in v2**: Diversity overhead too high
   - **Solution**: Reduce realization_count (try D=1)

### C.4 Decode Complexity Too High

**Symptoms**: Receiver CPU usage excessive, decode latency high

**Possible Causes**:
1. Generation size too large
   - **Solution**: Reduce generation size
2. Gaussian elimination triggered too often
   - **Solution**: Increase systematic prefix or coded redundancy
3. Decode attempted on every symbol arrival
   - **Solution**: Implement decode throttling (only retry after +2 symbols)

### C.5 Diversity Not Helping (NEW in v2)

**Symptoms**: Enabling diversity (D>1) doesn't improve success rate

**Possible Causes**:
1. Failures are random, not pattern-dependent
   - **Solution**: Disable diversity (D=1), increase redundancy instead
2. All realizations use same diversity mechanism
   - **Solution**: Try different diversity mechanisms
3. Diversity mechanism not effective for this channel
   - **Solution**: Experiment with different mechanisms (mask divergence, permutation, whitening)

**Diagnostic**: Compare per-realization success rates. If all realizations have similar rates, failures are likely random, not pattern-dependent.

---

## Appendix D: Diversity Mechanism Details (NEW in v2)

### D.1 Mask Divergence Implementation

**Concept**: Use different finder pattern masks for different realizations.

**Implementation**:
```python
def apply_mask_divergence(symbol_data, realization_id):
    mask_patterns = [
        MASK_PATTERN_A,  # realization 0
        MASK_PATTERN_B,  # realization 1
        MASK_PATTERN_C,  # realization 2
    ]
    mask = mask_patterns[realization_id % len(mask_patterns)]
    return encode_with_mask(symbol_data, mask)
```

**Benefit**: Reduces correlation between compression artifacts and specific mask patterns.

### D.2 Symbol Permutation Implementation

**Concept**: Reorder data bits before encoding.

**Implementation**:
```python
def apply_permutation(symbol_data, realization_id):
    permutation_seeds = [0, 12345, 67890]
    seed = permutation_seeds[realization_id % len(permutation_seeds)]
    rng = PRNG(seed)
    indices = list(range(len(symbol_data)))
    rng.shuffle(indices)
    return bytes([symbol_data[i] for i in indices])
```

**Receiver**: Apply inverse permutation after decode.

### D.3 Payload Whitening Implementation

**Concept**: XOR payload with PRNG sequence.

**Implementation**:
```python
def apply_whitening(symbol_data, realization_id):
    whitening_seeds = [0, 11111, 22222]
    seed = whitening_seeds[realization_id % len(whitening_seeds)]
    rng = PRNG(seed)
    whitening_sequence = rng.bytes(len(symbol_data))
    return xor_bytes(symbol_data, whitening_sequence)
```

**Receiver**: Apply same whitening (XOR is self-inverse).

### D.4 Spatial Permutation Implementation

**Concept**: Rearrange spatial layout of symbol tiles.

**Implementation**:
```python
def apply_spatial_permutation(symbol_data, realization_id, grid_size):
    permutation_patterns = [
        "standard",      # realization 0
        "checkerboard",  # realization 1
        "spiral",        # realization 2
    ]
    pattern = permutation_patterns[realization_id % len(permutation_patterns)]
    return rearrange_tiles(symbol_data, pattern, grid_size)
```

**Benefit**: Reduces correlation between spatial compression blocks and symbol boundaries.

---

**End of Specification**

