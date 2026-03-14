# OGRB Protocol Specification

**OGRB (Overlapping Generation Rateless Broadcast)**

Version: 1.0
Status: Draft
Date: 2026-03-09

---

## 1. Introduction

### 1.1 Purpose

This document specifies the OGRB (Overlapping Generation Rateless Broadcast) protocol for Screen-Airdrop. OGRB is designed to provide efficient, robust data transmission over visual broadcast channels with packet loss and limited feedback.

### 1.2 Scope

OGRB is not a single fixed-parameter protocol but a family of configurable operating points. It enables different trade-offs between:

- Recovery success rate
- Revisit pressure control
- Maximum throughput

### 1.3 Design Philosophy

OGRB addresses the limitations of frame-by-frame sequential transmission by:

1. Treating each frame as a lightweight symbol carrier
2. Moving primary recovery responsibility from frame-internal ECC to cross-frame erasure coding
3. Supporting mid-session join and continuous recovery through rateless coding
4. Maintaining short revisit cycles through overlapping generations

### 1.4 Why Not Whole-File Fountain Codes

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

### 3.1 Three-Layer Structure

OGRB is structured as three independent layers that MUST be kept separate:

#### Layer A: Physical Frame Layer

**Responsibilities:**
- Carry one symbol per frame
- Provide identifiable header
- Deliver payload if trustworthy
- Treat bad frames as erasures

**Non-responsibilities:**
- Cross-generation recovery
- Broadcast scheduling
- Global file completion judgment

#### Layer B: Generation Coding Layer

**Responsibilities:**
- Partition source data into small generations
- Maintain independent recovery state per generation
- Determine when a generation can be recovered

**Non-responsibilities:**
- Assume any specific frame must arrive
- Depend on visible epoch boundaries

#### Layer C: Broadcast Scheduling Layer

**Responsibilities:**
- Decide which generation to transmit
- Choose between systematic and coded symbols
- Allocate airtime between old and new generations

**Non-responsibilities:**
- Frame-level encoding details
- Symbol-level error correction

### 3.2 Layer Separation Requirements

Implementations MUST maintain clear boundaries:

1. Physical frame layer MUST NOT perform cross-generation recovery
2. Generation coding layer MUST NOT depend on specific frame arrival
3. Broadcast scheduling layer MUST NOT mix with frame encoding logic

---

## 4. Core Concepts

### 4.1 Symbols

**Source Symbol**: A fixed-size unit of original data (default: 512 bytes)

**Systematic Symbol**: A source symbol transmitted without encoding

**Coded Symbol**: A linear combination of source symbols within a generation

### 4.2 Generations

**Generation**: A group of consecutive source symbols that can be independently recovered

**Generation Size**: Number of source symbols in a generation (denoted `K`)

**Generation Overlap**: Fraction of symbols shared between consecutive generations

### 4.3 Symbol Types

Each transmitted frame carries either:
- A systematic symbol (direct copy of source data)
- A coded symbol (XOR combination of multiple source symbols)

---

## 5. Parameters

### 5.1 Core Parameters

| Parameter | Symbol | Type | Description |
|-----------|--------|------|-------------|
| Symbol Size | `S` | bytes | Size of each source symbol |
| Generation Size | `K` | count | Number of symbols per generation |
| Generation Overlap | `α` | fraction | Overlap between consecutive generations |
| Systematic Prefix | `P` | count | Number of systematic symbols sent first |
| Coded Redundancy | `R` | ratio | Total symbols sent / generation size |
| Max Active Generations | `G` | count | Maximum concurrent active generations |
| Old/New Ratio | `β` | ratio | Airtime bias toward older generations |
| Decode Margin | `M` | count | Extra symbols required before decode attempt |

### 5.2 Derived Parameters

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

---

## 6. Default Parameters

### 6.1 Baseline Configuration

If not otherwise specified, implementations SHOULD start from these values:

```
symbol_size = 512 bytes
generation_size = 20~24
generation_overlap = 0.125~0.25
systematic_prefix = 6~8
coded_redundancy = 1.15~1.25
max_active_generations = 2
old_new_ratio = 1.5
decode_margin = 1
```

### 6.2 Rationale

These defaults represent a **balanced** profile suitable for:
- Local screen capture scenarios
- Limited capture FPS (10-18 fps)
- Moderate packet loss (5-15%)
- Trade-off between throughput and robustness

---

## 7. Frame Header Format

### 7.1 Required Header Fields

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
| `coding_seed` | uint32 | PRNG seed for coded symbol (valid for coded) |
| `degree` | uint8 | Number of source symbols XORed (valid for coded) |
| `header_crc` | uint16 | CRC-16 of header fields |
| `payload_crc` | uint16 | CRC-16 of payload data |

### 7.2 Header Design Requirements

1. **Generation Attribution**: Generation membership MUST be explicitly visible
2. **Symbol Type Distinction**: Systematic vs coded MUST be unambiguous
3. **Separate Validation**: Header and payload validity MUST be independently checkable
4. **Compact Encoding**: Header SHOULD fit within control plane capacity

### 7.3 Header vs Payload Validation

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

2. **Coded Phase**: Generate and send coded symbols until:
   - Total symbols sent reaches `K × R`
   - Or scheduler switches to different generation

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

### 8.5 Broadcast Scheduler

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
   - Send next systematic symbol
3. Else:
   - Generate and send coded symbol

**Generation Advancement**:

Advance to new generation when:
- Current generation has sent `K × R` total symbols
- Or timeout threshold reached (optional)

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

### 9.2 Generation State

For each generation `g`, receiver MUST maintain:

| State Field | Type | Description |
|-------------|------|-------------|
| `known_systematic_symbols` | set[int] | Indices of received systematic symbols |
| `known_coded_symbols` | list[CodedSymbol] | Received coded symbols with metadata |
| `decode_attempted` | bool | Whether decode has been tried |
| `decode_completed` | bool | Whether generation is fully recovered |
| `last_progress_ts` | timestamp | Last time new symbol was received |

**CodedSymbol Structure**:
```python
@dataclass
class CodedSymbol:
    seed: int
    degree: int
    indices: list[int]  # which source symbols were XORed
    payload: bytes
```

### 9.3 Decode Triggering

**Decode Condition**:

Attempt decode when:
```
len(known_systematic_symbols) + len(known_coded_symbols) >= K + M
```

where `M` is decode margin (default: 1)

**Decode Ordering** (SHOULD follow this priority):

1. **Direct Recovery**: If all `K` systematic symbols received, output immediately
2. **Lightweight Recovery**: Try peeling decoder or belief propagation
3. **Gaussian Elimination**: Fallback to full matrix solve if needed

**Important**: Receiver MUST NOT re-attempt decode on every new symbol. SHOULD only retry when:
- New symbols arrive after previous decode failure
- Sufficient additional symbols accumulated (e.g., +2 symbols)

### 9.4 Symbol Output

When generation `g` is successfully decoded:

1. Mark `decode_completed = true`
2. Output `K` source symbols in order
3. Pass to reassembly layer
4. Optionally: free generation state to reclaim memory

### 9.5 Timeout and Cleanup

Receiver SHOULD implement timeout for stalled generations:

- If `current_time - last_progress_ts > timeout_threshold`:
  - Mark generation as failed
  - Report to upper layer
  - Free resources

---

## 10. Three Core Trade-offs

### 10.1 Forward Progress

**Definition**: How quickly new data enters the transmission

**Controlled By**:
- `generation_overlap` (α): Higher overlap → slower progress
- `max_active_generations` (G): More active → slower per-generation progress
- `old_new_ratio` (β): Higher ratio → more time on old generations

**Question Answered**: Does sender keep moving forward or get stuck revisiting old data?

### 10.2 Revisit Pressure

**Definition**: How quickly old generations receive additional recovery opportunities

**Controlled By**:
- `generation_overlap` (α): Higher overlap → more revisit paths
- `old_new_ratio` (β): Higher ratio → more frequent revisits
- `max_active_generations` (G): More active → distributed revisit opportunities

**Question Answered**: If a generation is almost complete, how long until it gets another useful symbol?

### 10.3 Recovery Robustness

**Definition**: Probability that a generation completes successfully under packet loss

**Controlled By**:
- `generation_size` (K): Smaller → faster completion, less loss exposure
- `coded_redundancy` (R): Higher → more recovery capacity
- `systematic_prefix` (P): Higher → faster startup, better for sparse sampling
- `decode_margin` (M): Higher → more conservative decode triggering

**Question Answered**: Will this generation complete or get stuck?

### 10.4 Parameter Interaction

These trade-offs are NOT independent:

- Increasing overlap improves revisit pressure BUT reduces forward progress
- Increasing redundancy improves robustness BUT reduces raw throughput
- Increasing active generations distributes revisit BUT slows per-generation completion

**Key Insight**: There is no single "optimal" parameter set. Choice depends on:
- Sender FPS
- Capture FPS
- Packet loss rate
- Latency requirements

---

## 11. Operating Profiles

### 11.1 Profile Overview

OGRB defines three standard profiles optimized for different scenarios. Implementations SHOULD support all three profiles and allow users to select via configuration.

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
max_active_generations = 2
old_new_ratio = 2.0~2.5 (recommended: 2.0)
decode_margin = 2
```

**Characteristics**:

- **Small generations**: Reduces time-to-completion, limits loss exposure
- **High coded redundancy**: Prioritizes recovery success over raw throughput
- **Strong old-generation bias**: Shortens tail latency for nearly-complete generations
- **Moderate overlap (25%)**: Provides secondary recovery path without excessive cost

**Typical Performance**:
- Generation size: ~7 KB
- Step size: ~5.25 KB
- Effective throughput: 60-70% of raw capacity
- Recovery success rate: >95% under 20% loss

**Design Rationale**:

This profile prioritizes "complete this generation quickly" over "push forward aggressively". The old/new ratio of 2.0 means sender spends twice as much airtime on older generations, ensuring they complete before moving on.

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
max_active_generations = 2
old_new_ratio = 1.5
decode_margin = 1
```

**Characteristics**:

- **Medium generations**: Avoids frequent generation switching overhead
- **Low-to-medium overlap**: Maintains forward progress while providing limited revisit
- **Higher systematic prefix**: Better for receiver sparse sampling scenarios
- **Moderate redundancy**: Balances efficiency and recovery capability

**Typical Performance**:
- Generation size: ~11 KB
- Step size: ~9.6 KB (at α=0.125)
- Effective throughput: 75-85% of raw capacity
- Recovery success rate: >90% under 10% loss

**Design Rationale**:

This profile is optimized for the common case where receiver does sparse sampling of sender's output stream. Higher systematic prefix ensures early symbols are more likely to be useful. Lower overlap (12.5%) prioritizes forward progress.

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
max_active_generations = 1
old_new_ratio = 1.0 (no bias)
decode_margin = 0
```

**Characteristics**:

- **Large generations**: Maximizes net efficiency, reduces switching overhead
- **Zero overlap**: Maximum forward progress speed
- **Minimal redundancy**: Only essential protection
- **Single active generation**: No airtime fragmentation

**Typical Performance**:
- Generation size: ~15 KB
- Step size: ~15 KB (no overlap)
- Effective throughput: 90-95% of raw capacity
- Recovery success rate: >85% under 5% loss

**Design Rationale**:

This profile sacrifices worst-case recovery experience for maximum raw throughput. It assumes the channel is clean enough that aggressive parameters won't cause frequent generation failures.

### 11.5 Profile Selection Guidelines

| Scenario | Sender FPS | Loss Rate | Capture FPS | Recommended Profile |
|----------|-----------|-----------|-------------|---------------------|
| Remote server | 5-10 | 15-30% | 10-15 | **Robust** |
| Local macOS | 15-25 | 5-15% | 10-18 | **Balanced** |
| Ideal lab | >25 | <5% | >20 | **Throughput** |
| Unknown | Any | Unknown | Any | **Balanced** (safe default) |

### 11.6 Profile Customization

Users MAY override individual parameters while using a profile as baseline:

```bash
# Start from balanced, but increase redundancy
--ogrb-profile balanced --ogrb-coded-redundancy 1.4
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
4. Only then consider increasing `overlap`

**Example**:

Instead of:
```
generation_size = 24, overlap = 0.5, redundancy = 1.2
```

Prefer:
```
generation_size = 16, overlap = 0.25, redundancy = 1.5
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

### 12.4 No Sender-Side Adaptation

**Principle**: First version MUST use static profiles, NOT sender-side adaptation.

**Rationale**:
- Visual broadcast channel typically lacks reliable feedback path
- Sender cannot reliably know:
  - Actual packet loss rate
  - Receiver decode progress
  - Generation completion status
- Static profiles with offline benchmarking are more predictable

**Future Extension**:

Sender-side adaptation MAY be added later if:
- Reliable reverse control channel is established
- Receiver can report generation completion status
- Adaptation logic is thoroughly benchmarked

---

## 13. Performance Metrics

### 13.1 Required Metrics

Implementations MUST track and report:

**Sender Metrics**:
- `frames_sent`: Total frames transmitted
- `systematic_sent`: Count of systematic symbols sent
- `coded_sent`: Count of coded symbols sent
- `generations_started`: Number of generations entered
- `generations_completed`: Number of generations fully transmitted

**Receiver Metrics**:
- `frames_received`: Total frames captured
- `bad_header_count`: Frames with invalid header CRC
- `bad_payload_count`: Frames with invalid payload CRC
- `good_frames`: Frames with both header and payload valid
- `generations_decoded`: Number of generations successfully recovered
- `generations_failed`: Number of generations that timed out

### 13.2 Derived Metrics

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

### 13.3 Benchmark Requirements

When benchmarking OGRB implementations, reports SHOULD include:

1. **Environment Description**:
   - Sender FPS
   - Capture FPS
   - Simulated or measured loss rate
   - Test duration

2. **Configuration**:
   - Profile used (or custom parameters)
   - All parameter values

3. **Results**:
   - All required metrics (Section 13.1)
   - All derived metrics (Section 13.2)
   - Latency distribution (time from generation start to completion)

---

## 14. Implementation Requirements

### 14.1 Mandatory Requirements (MUST)

Implementations MUST satisfy the following:

1. **Layer Separation**:
   - Physical frame layer, generation coding layer, and broadcast scheduling layer MUST be independently testable
   - No cross-layer coupling beyond defined interfaces

2. **Header Validation**:
   - Header CRC MUST be validated before payload decode
   - Invalid headers MUST be discarded immediately

3. **Generation State Tracking**:
   - Receiver MUST maintain state for each active generation
   - State MUST include at minimum: systematic symbols, coded symbols, decode status, last progress timestamp

4. **Profile Support**:
   - MUST support at least the "balanced" profile
   - SHOULD support all three standard profiles (robust, balanced, throughput)

5. **Metrics Reporting**:
   - MUST track all required metrics (Section 13.1)
   - MUST provide mechanism to export metrics for analysis

### 14.2 Recommended Requirements (SHOULD)

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

### 14.3 Prohibited Behaviors (MUST NOT)

Implementations MUST NOT:

1. **Sender-Side Adaptation**:
   - MUST NOT implement sender-side adaptation in first version
   - MUST NOT assume reliable feedback channel exists

2. **Cross-Generation Recovery**:
   - Physical frame layer MUST NOT perform cross-generation recovery
   - Generation coding layer MUST NOT depend on specific frame arrival order

3. **Implicit Assumptions**:
   - MUST NOT assume all frames will be received
   - MUST NOT assume epoch boundaries are visible
   - MUST NOT assume sender and receiver clocks are synchronized

---

## 15. CLI Interface

### 15.1 Sender CLI

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
  --ogrb-max-active-generations 2 \
  --ogrb-old-new-ratio 1.5 \
  --input ./file.tar.gz
```

### 15.2 Receiver CLI

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

### 15.3 Parameter Naming Convention

All OGRB-specific parameters SHOULD use the `--ogrb-` prefix to avoid namespace collision with other protocols.

**Standard Parameter Names**:
- `--ogrb-profile`: Profile selection (robust/balanced/throughput)
- `--ogrb-symbol-size`: Symbol size in bytes
- `--ogrb-generation-size`: Number of symbols per generation
- `--ogrb-generation-overlap`: Overlap fraction (0.0-0.5)
- `--ogrb-systematic-prefix`: Number of systematic symbols sent first
- `--ogrb-coded-redundancy`: Total symbols / generation size ratio
- `--ogrb-max-active-generations`: Maximum concurrent active generations
- `--ogrb-old-new-ratio`: Airtime bias toward older generations
- `--ogrb-decode-margin`: Extra symbols required before decode attempt

---

## 16. Testing Requirements

### 16.1 Unit Tests

Implementations MUST include unit tests for:

1. **Generation Partitioning**:
   - Verify correct symbol ranges for each generation
   - Test overlap calculation
   - Test step size computation

2. **Coded Symbol Generation**:
   - Verify deterministic generation from seed
   - Test degree distribution
   - Verify XOR correctness

3. **Header Encoding/Decoding**:
   - Test all header fields
   - Verify CRC calculation
   - Test invalid header rejection

4. **Decode Logic**:
   - Test direct recovery (all systematic received)
   - Test peeling decoder
   - Test Gaussian elimination fallback

### 16.2 Integration Tests

Implementations SHOULD include integration tests for:

1. **Synthetic Roundtrip**:
   - Generate test data
   - Encode with OGRB sender
   - Decode with OGRB receiver (no loss)
   - Verify bit-exact recovery

2. **Lossy Channel Simulation**:
   - Simulate packet loss at various rates (5%, 10%, 20%)
   - Verify generation recovery success rate
   - Measure goodput vs raw throughput

3. **Profile Validation**:
   - Test all three standard profiles
   - Verify parameter consistency
   - Measure performance characteristics

### 16.3 Benchmark Tests

Implementations SHOULD support benchmark modes:

1. **Replay Benchmark**:
   - Use pre-captured frame sequences
   - Measure decode performance
   - Compare across profiles

2. **End-to-End Benchmark**:
   - Real screen capture
   - Measure actual throughput
   - Track generation completion latency

---

## 17. Examples

### 17.1 Example: Balanced Profile Calculation

**Configuration**:
```
symbol_size = 512 bytes
generation_size = 22
generation_overlap = 0.125
systematic_prefix = 6
coded_redundancy = 1.2
```

**Derived Values**:
```
step_size = 22 × (1 - 0.125) = 19.25 symbols
generation_data_size = 22 × 512 = 11,264 bytes ≈ 11 KB
step_data_size = 19.25 × 512 = 9,856 bytes ≈ 9.6 KB
total_symbols_per_gen = 22 × 1.2 = 26.4 symbols
coded_symbols_per_gen = 26.4 - 6 = 20.4 symbols
```

**Generation Boundaries** (first 3 generations):
```
Generation 0: symbols [0, 21]     (22 symbols)
Generation 1: symbols [19, 40]    (22 symbols, overlap with gen 0: [19, 21])
Generation 2: symbols [38, 59]    (22 symbols, overlap with gen 1: [38, 40])
```

### 17.2 Example: Transmission Sequence

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

### 17.3 Example: Receiver Decode Scenario

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

---

## 18. Comparison with Alternatives

### 18.1 vs Sequential Transmission

**Sequential** (current basic/compact):
- Each frame = complete packet
- Lost frame = wait for next epoch
- Heavy frame-internal ECC

**OGRB**:
- Each frame = one symbol
- Lost frame = erasure, recoverable via coding
- Lightweight frame validation, heavy cross-frame coding

**Advantage**: OGRB provides better loss tolerance and eliminates epoch waiting.

### 18.2 vs Whole-File Fountain

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

**Advantage**: OGRB provides predictable latency and manageable complexity.

### 18.3 vs Fixed-Rate Block Codes

**Fixed-Rate Block Codes** (e.g., Reed-Solomon):
- Fixed redundancy ratio
- Optimal for known loss rate
- Cannot adapt to varying conditions

**OGRB**:
- Rateless coding (can generate unlimited coded symbols)
- Works across varying loss rates
- Sender can continue transmitting until receiver signals completion

**Advantage**: OGRB handles unknown or varying loss rates gracefully.

---

## 19. Future Extensions

### 19.1 Potential Enhancements

The following features are NOT part of the initial specification but MAY be added in future versions:

1. **Sender-Side Adaptation**:
   - Dynamic profile switching based on feedback
   - Requires reliable reverse control channel
   - Should be thoroughly benchmarked before deployment

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

### 19.2 Non-Goals

The following are explicitly NOT goals for OGRB:

1. **Real-Time Streaming**: OGRB is optimized for file transfer, not low-latency streaming
2. **Bidirectional Communication**: No built-in ACK/NACK mechanism
3. **Encryption**: Security should be handled at application layer
4. **Compression**: Data should be compressed before OGRB encoding

---

## 20. Glossary

**Airtime**: The transmission time allocated to a particular generation or symbol type.

**Coded Symbol**: A linear combination (XOR) of multiple source symbols within a generation.

**Decode Margin**: Extra symbols required beyond the minimum (K) before attempting decode.

**Degree**: Number of source symbols XORed together to create a coded symbol.

**Erasure**: A lost or corrupted frame treated as missing data (position known, value unknown).

**Generation**: A group of consecutive source symbols that can be independently recovered.

**Goodput**: Effective data throughput measured as successfully recovered data per unit time.

**Overlap**: Fraction of symbols shared between consecutive generations.

**Peeling Decoder**: Lightweight iterative decoder that resolves symbols one at a time.

**Profile**: A named set of parameter values optimized for a specific scenario.

**Rateless Code**: A code that can generate unlimited coded symbols from a fixed set of source symbols.

**Revisit Pressure**: How frequently old generations receive additional recovery opportunities.

**Source Symbol**: A fixed-size unit of original data (default: 512 bytes).

**Step Size**: Number of symbols advanced between consecutive generation starts.

**Systematic Symbol**: A source symbol transmitted without encoding (direct copy).

---

## 21. References

### 21.1 Related Protocols

- **LT Codes**: Luby Transform codes, foundation for rateless coding
- **Raptor Codes**: Systematic rateless codes with pre-coding
- **RaptorQ**: IETF RFC 6330, standardized fountain code

### 21.2 Relevant Literature

- Luby, M. (2002). "LT codes". *Proceedings of the 43rd Annual IEEE Symposium on Foundations of Computer Science*.
- Shokrollahi, A. (2006). "Raptor codes". *IEEE Transactions on Information Theory*.
- MacKay, D. J. C. (2005). "Fountain codes". *IEE Proceedings - Communications*.

### 21.3 Screen-Airdrop Documentation

- [throughput_optimization_plan.md](./throughput_optimization_plan.md): Overall optimization strategy
- [protocol_efficiency_report.md](./protocol_efficiency_report.md): Single-frame efficiency analysis
- [benchmark_status.md](./benchmark_status.md): Current benchmark results

---

## 22. Revision History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-03-09 | Initial specification |

---

## Appendix A: Parameter Quick Reference

### A.1 Robust Profile

```
symbol_size = 512
generation_size = 14
generation_overlap = 0.25
systematic_prefix = 4
coded_redundancy = 1.5
max_active_generations = 2
old_new_ratio = 2.0
decode_margin = 2

# Derived
step_size = 10.5 symbols ≈ 5.25 KB
generation_data_size = 7 KB
total_symbols_per_gen = 21
coded_symbols_per_gen = 17
```

### A.2 Balanced Profile

```
symbol_size = 512
generation_size = 22
generation_overlap = 0.125
systematic_prefix = 6
coded_redundancy = 1.2
max_active_generations = 2
old_new_ratio = 1.5
decode_margin = 1

# Derived
step_size = 19.25 symbols ≈ 9.6 KB
generation_data_size = 11 KB
total_symbols_per_gen = 26.4
coded_symbols_per_gen = 20.4
```

### A.3 Throughput Profile

```
symbol_size = 512
generation_size = 30
generation_overlap = 0
systematic_prefix = 10
coded_redundancy = 1.08
max_active_generations = 1
old_new_ratio = 1.0
decode_margin = 0

# Derived
step_size = 30 symbols = 15 KB
generation_data_size = 15 KB
total_symbols_per_gen = 32.4
coded_symbols_per_gen = 22.4
```

---

## Appendix B: Implementation Checklist

### B.1 Sender Implementation

- [ ] Generation partitioning with overlap
- [ ] Systematic symbol transmission
- [ ] Coded symbol generation (with PRNG seed)
- [ ] Degree distribution (Robust Soliton or similar)
- [ ] Broadcast scheduler with airtime allocation
- [ ] Active generation set management
- [ ] Header encoding with CRC
- [ ] Payload CRC calculation
- [ ] Metrics tracking (frames sent, generations started, etc.)
- [ ] Profile support (at least balanced)
- [ ] CLI parameter parsing

### B.2 Receiver Implementation

- [ ] Frame capture and decode
- [ ] Header CRC validation
- [ ] Payload CRC validation
- [ ] Generation state management
- [ ] Systematic symbol storage
- [ ] Coded symbol storage with metadata
- [ ] Decode triggering logic
- [ ] Direct recovery (all systematic received)
- [ ] Peeling decoder
- [ ] Gaussian elimination fallback
- [ ] Generation timeout and cleanup
- [ ] Metrics tracking (frames received, generations decoded, etc.)
- [ ] Profile support
- [ ] CLI parameter parsing

### B.3 Testing

- [ ] Unit tests for generation partitioning
- [ ] Unit tests for coded symbol generation
- [ ] Unit tests for header encoding/decoding
- [ ] Unit tests for decode logic
- [ ] Integration test: synthetic roundtrip (no loss)
- [ ] Integration test: lossy channel simulation (5%, 10%, 20%)
- [ ] Integration test: all three profiles
- [ ] Benchmark: replay mode
- [ ] Benchmark: end-to-end with real screen capture

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

### C.2 High Generation Failure Rate

**Symptoms**: Many generations timeout without completing

**Possible Causes**:
1. Generation size too large for loss rate
   - **Solution**: Reduce generation size
2. Coded redundancy insufficient
   - **Solution**: Increase coded redundancy
3. Max active generations too high, fragmenting airtime
   - **Solution**: Reduce to 2 or 1

### C.3 Slow Forward Progress

**Symptoms**: Sender keeps revisiting old generations, new data not advancing

**Possible Causes**:
1. Overlap too high
   - **Solution**: Reduce overlap (try 0.125 instead of 0.25)
2. Old/new ratio too high
   - **Solution**: Reduce old/new ratio (try 1.5 instead of 2.0)
3. Too many active generations
   - **Solution**: Reduce max active generations

### C.4 Decode Complexity Too High

**Symptoms**: Receiver CPU usage excessive, decode latency high

**Possible Causes**:
1. Generation size too large
   - **Solution**: Reduce generation size
2. Gaussian elimination triggered too often
   - **Solution**: Increase systematic prefix or coded redundancy
3. Decode attempted on every symbol arrival
   - **Solution**: Implement decode throttling (only retry after +2 symbols)

---

**End of Specification**

