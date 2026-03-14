# Protocol Efficiency Report

## Scope

This report answers a narrow question:

> Why is the current `basic` / `compact` protocol family using much less single-frame payload than a large QR Code, even though the protocol looks simpler?

The comparison is intentionally **theoretical and code-based**:

- current project implementation only
- current `basic` / `compact` layouts
- current four ECC levels: `L / M / Q / H`
- QR Code compared as a standards baseline at **Version 40** in byte mode

This is not an end-to-end throughput report. It is a **single-frame efficiency report**.

## Important Comparison Note

There are two slightly different area-counting conventions in play:

- this report's `frame_w * frame_h` for `basic/compact` includes the outer quiet zone
- the standard QR Code version size `177x177` does **not** include the required quiet zone outside the symbol

So QR's published `Version 40 = 177x177` payload table is already somewhat favorable to QR in area accounting.

That said, even after accounting for this difference, the main qualitative conclusions below do not change:

- `Q/H` are where the current protocol family loses badly
- the dominant loss is frame-internal ECC efficiency
- `compact` is a real improvement over `basic`

## Executive Summary

The current protocol family underuses frame area primarily for three reasons:

1. **Frame-internal ECC is very expensive**
   - `L/M/Q/H` currently map to repetition counts `1/2/3/4`
   - this is much less efficient than QR's block ECC

2. **Static geometry overhead is non-trivial**
   - quiet zone
   - four corner finders
   - guard band
   - timing rails
   - format/layout regions

3. **Sender applies an additional 0.9 safety cap**
   - `safe_chunk_size = floor(frame_payload_cap * 0.9)`

The result is:

- `compact` is better than `basic`
- but both still have lower single-frame payload density than large QR
- especially at `Q/H`

## Current ECC Model

The current implementation uses repetition coding:

- `L -> rep=1`
- `M -> rep=2`
- `Q -> rep=3`
- `H -> rep=4`

Source:
- [protocol_basic.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/common/protocol_basic.py)

This is the single biggest reason the current protocol family loses net payload efficiency.

## Layout Formulas

For both `basic` and `compact`, total frame size is:

`frame_w = 2*quiet + 2*finder + 2*guard + grid_w`

`frame_h = 2*quiet + 2*finder + 2*guard + grid_h`

Current defaults:

- `basic`: `quiet=4`, `finder=9`, `guard=2`
- `compact`: `quiet=4`, `finder=7`, `guard=1`

Sources:
- [layout_basic.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/common/layout_basic.py)
- [layout_compact.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/common/layout_compact.py)

## Capacity Table

### Same Grid: `160x96`

#### `basic 160x96`

| ECC | Frame Size | Total Modules | Payload Cap (B) | Safe Chunk (B) | Effective bits/module |
| --- | --- | ---: | ---: | ---: | ---: |
| L | 190x126 | 23940 | 1876 | 1688 | 0.6269 |
| M | 190x126 | 23940 | 916 | 824 | 0.3061 |
| Q | 190x126 | 23940 | 596 | 536 | 0.1992 |
| H | 190x126 | 23940 | 436 | 392 | 0.1457 |

#### `compact 160x96`

| ECC | Frame Size | Total Modules | Payload Cap (B) | Safe Chunk (B) | Effective bits/module |
| --- | --- | ---: | ---: | ---: | ---: |
| L | 184x120 | 22080 | 1876 | 1688 | 0.6797 |
| M | 184x120 | 22080 | 916 | 824 | 0.3319 |
| Q | 184x120 | 22080 | 596 | 536 | 0.2159 |
| H | 184x120 | 22080 | 436 | 392 | 0.1580 |

Interpretation:

- `compact` does **not** increase payload bytes at the same grid
- it improves **area efficiency**
- this is why same-grid comparisons mostly show runtime/geometry gains, not payload gains

### Footprint-Matched: `basic 160x96` vs `compact 166x102`

This is the fairer comparison when the outer visual footprint is held constant.

#### `compact 166x102`

| ECC | Frame Size | Total Modules | Payload Cap (B) | Safe Chunk (B) | Effective bits/module |
| --- | --- | ---: | ---: | ---: | ---: |
| L | 190x126 | 23940 | 2072 | 1864 | 0.6924 |
| M | 190x126 | 23940 | 1014 | 912 | 0.3388 |
| Q | 190x126 | 23940 | 661 | 594 | 0.2209 |
| H | 190x126 | 23940 | 485 | 436 | 0.1621 |

Interpretation:

- this is the first comparison where `compact` shows a real single-frame payload gain
- at `Q`, `compact` increases safe payload from `536 B` to `594 B`
- payload gain: `594 / 536 ≈ 1.108`

### Larger Grid: `224x136`

#### `basic 224x136`

| ECC | Frame Size | Total Modules | Payload Cap (B) | Safe Chunk (B) | Effective bits/module |
| --- | --- | ---: | ---: | ---: | ---: |
| L | 254x166 | 42164 | 3764 | 3387 | 0.7142 |
| M | 254x166 | 42164 | 1860 | 1674 | 0.3529 |
| Q | 254x166 | 42164 | 1225 | 1102 | 0.2324 |
| H | 254x166 | 42164 | 908 | 817 | 0.1723 |

#### `compact 224x136`

| ECC | Frame Size | Total Modules | Payload Cap (B) | Safe Chunk (B) | Effective bits/module |
| --- | --- | ---: | ---: | ---: | ---: |
| L | 248x160 | 39680 | 3764 | 3387 | 0.7589 |
| M | 248x160 | 39680 | 1860 | 1674 | 0.3750 |
| Q | 248x160 | 39680 | 1225 | 1102 | 0.2470 |
| H | 248x160 | 39680 | 908 | 817 | 0.1831 |

Interpretation:

- `224x136 + Q` really does cap out at `1225 B`, with `1102 B` safe payload
- this is not a tuning mistake
- it is the current protocol's true frame-level payload limit

## QR Code Baseline

For QR Code Version 40 in byte mode:

| ECC | Payload (B) | Total Modules | Effective bits/module |
| --- | ---: | ---: | ---: |
| L | 2953 | 31329 | 0.7541 |
| M | 2331 | 31329 | 0.5952 |
| Q | 1663 | 31329 | 0.4247 |
| H | 1273 | 31329 | 0.3251 |

Interpretation:

- QR Code is especially strong at `Q` and `H`
- compared to `compact 224x136`, QR still wins by a large margin in payload density:
  - `Q`: `0.4247 / 0.2470 ≈ 1.72x`
  - `H`: `0.3251 / 0.1831 ≈ 1.78x`

## Why `L` Can Match Or Slightly Beat QR

This is the part that initially looks counterintuitive.

At `L`, the current protocol family is using:

- `rep = 1`
- no frame-internal redundancy inflation from repetition ECC

That means the payload cap is mainly limited by:

- geometry overhead
- header bytes
- sender safety cap

In contrast, QR Version 40 still spends substantial area on:

- finder patterns
- alignment patterns
- timing patterns
- format/version information
- Reed-Solomon parity and block structure

So at `L`, where the current protocol has **no repetition penalty**, a large custom data grid can reach payload density similar to or even slightly above QR's official byte-mode capacity.

For example:

- `compact 224x136`
  - `Payload Cap = 3764 B`
  - `Frame Size = 248x160`
  - `Effective bits/module = 0.7589`
- `QR Version 40-L`
  - `Payload = 2953 B`
  - `Version Size = 177x177`
  - `Effective bits/module = 0.7541`

This does **not** mean the current protocol is generally more efficient than QR.

It means:

1. at `L`, the current protocol is no longer being crushed by repetition ECC
2. QR's fixed function-pattern overhead is still real, even at `L`
3. the real gap appears when moving to `M/Q/H`, because QR's ECC scales much more efficiently than repetition coding

So the correct interpretation is:

- `L` is the one regime where the current frame format is structurally competitive
- `M/Q/H` are the regimes where the current frame-internal ECC model falls behind hard

## Loss Waterfall: `compact 224x136 + Q`

This is the clearest example because it matches the configuration under discussion.

### Step 1: Start from the raw payload grid

- grid modules: `224 * 136 = 30464`

If each payload module carried one independent bit, this would be:

- `30464 bits`

### Step 2: Apply repetition ECC

At `Q`, the repetition factor is `3`.

So decoded bits become:

- `30464 / 3 = 10154 bits`
- `≈ 1269 bytes`

This is the largest single loss.

### Step 3: Subtract frame header

Current header size:

- `HEADER_SIZE = 42 bytes`

So:

- `1269 - 42 ≈ 1227 bytes`

Actual code-derived cap:

- `1225 bytes`

This matches the implementation.

### Step 4: Apply sender safety cap

Current sender rule:

- `safe_chunk_size = floor(frame_payload_cap * 0.9)`

So:

- `1225 * 0.9 = 1102`

Final safe payload:

- `1102 bytes`

## What Actually Dominates The Loss

### 1. ECC dominates

At `Q`, repetition coding throws away about two thirds of the raw payload-grid bit capacity.

This is the biggest reason current payload density is low.

### 2. Static structure matters, but is not the main problem

For `compact 224x136`:

- total modules: `39680`
- payload-grid modules: `30464`
- grid occupancy: `30464 / 39680 ≈ 76.8%`

So geometry overhead costs about:

- `23.2%` of total frame area

This is meaningful, but still much smaller than the ECC loss.

### 3. Safe cap is the final trimming layer

The 0.9 sender cap cuts another:

- `10%` of frame payload cap

This matters, but it is not the primary cause of low density.

## Why Simplicity Does Not Help Here

The protocol is simpler than QR in engineering structure, but that does not mean it is more efficient.

Current simplicity buys:

- easier experimentation
- easier layout changes
- easier locator/debug iteration

It does **not** buy:

- high coding efficiency
- near-optimal frame utilization

QR is more complex, but its complexity is specifically optimized for information density and ECC efficiency.

## Can We Reuse QR's ECC?

Yes, in the important sense.

No, in the literal drop-in sense.

### What cannot be directly reused

QR's full coding pipeline is tightly coupled to:

- QR codewords
- block partitioning
- Reed-Solomon parity layout
- interleaving rules
- placement rules inside the QR matrix

So the project cannot simply "switch to QR ECC" by copying the whole QR encoder/decoder and keeping the current frame format unchanged.

### What can be reused

The useful part to borrow is the **ECC family and framing strategy**:

- systematic Reed-Solomon over bytes
- block partitioning
- optional interleaving to spread burst errors

That is absolutely compatible with the current protocol family.

In other words, the current protocol can keep:

- its own layout
- its own finder/timing system
- its own header
- its own sender/receiver pipeline

and replace only the current repetition coding with something QR-like in spirit:

- byte-oriented block ECC
- stronger redundancy efficiency
- much smaller payload tax at `M/Q/H`

### Pragmatic migration path

The most defensible path is:

1. keep the current frame layout unchanged
2. keep frame CRC unchanged
3. replace repetition coding with a systematic byte-level ECC
4. only after that revisit `gray4` / `layered`

This order matters because right now the biggest payload loss is not modulation depth. It is frame-internal ECC inefficiency.

### Why this matters

If local screen-capture testing shows that `L` already works reliably, then the project has strong evidence that:

- heavy frame-internal repetition is not the right default for this channel
- reliability should shift upward to:
  - lightweight frame CRC
  - more efficient frame ECC
  - later, outer erasure / fountain protection

That is a much better engineering direction than continuing to accept 3x/4x repetition overhead.

## Main Conclusions

1. `compact` is a real improvement over `basic`
   - same-grid: better area efficiency
   - footprint-matched: larger payload
   - real screen benchmark: better effective receive-side rate

2. `L` is now a special case
   - if the screen-capture channel can reliably support `L`, the current protocol is already structurally competitive there
   - `L` is therefore worth treating as a first-class benchmark target, not just a low-redundancy curiosity

3. Current `basic/compact` still underperform large QR in single-frame payload density at `M/Q/H`
   - especially at `Q` and `H`

4. The primary bottleneck is not finder/guard geometry alone
   - it is the **frame-internal repetition ECC**

5. If the goal is to beat QR on single-frame information density, the next meaningful steps are:
   - make `L` a real benchmark track for the screen-capture channel
   - replace repetition ECC with a much more efficient frame-level code
   - then move to `gray4`
   - then `layered`

6. If the goal is to beat QR on system-level usefulness rather than single-frame density, then future leverage is more likely to come from:
   - multi-window parallelism
   - erasure / fountain broadcast recovery
   - modulation schemes tailored to the screen-capture channel

## Recommended Next Question

The next high-value question is no longer:

> "Can we squeeze a little more out of current `compact`?"

It is:

> "Do we want to optimize for single-frame information density, or for whole-system broadcast behavior?"

Those two goals are no longer aligned enough to treat as the same problem.
