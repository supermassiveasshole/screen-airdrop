## Gray4 Sleep Summary

Date: 2026-03-15

### Current State

Gray4 is still not reliable enough in live screen capture, even when the test
conditions are relaxed.

What we confirmed tonight:

1. A small number of frames/chunks can remain undecodable even under looser
   settings.
2. Some of the recent decoder complexity increased cost a lot without solving
   the remaining bad-frame problem.
3. One sender-side rendering experiment made live decode worse and has been
   reverted.
4. Repetition-based protection is a weak baseline, not a good long-term ECC
   strategy, and the sender should derive effective chunk size from frame
   capacity and fill ratio instead of relying on a hidden default byte count.

### Confirmed Findings

#### 1. Relaxed settings still do not guarantee full recovery

Even after lowering sender FPS and reducing load on the receiver side, a few
chunks can still remain permanently missing.

This means the remaining failures are not only a "pipeline too slow" problem.
At least part of the issue is content-specific or sampling-margin-specific:

- certain frames are stable bad cases
- neighboring frames can decode correctly
- the same bad chunks can remain missing in both live pipeline and captured
  replay

So the failure mode is now:

- not primarily queue pressure
- not primarily worker count
- not primarily timeout configuration
- but a small set of fragile frames/chunks

Additional follow-up:

- even when conditions are made very conservative, Gray4 can still show a small
  number of persistent bad chunks
- when conditions are made extremely conservative, transfers can complete, but
  that does not validate repetition as an efficient ECC design
- a later follow-up confirmed that changing the data-frame mask across epochs
  can eliminate some previously persistent bad chunks
- this means at least part of the remaining failure mode is fixed-pattern
  fragility under a static display/capture setup, not simply "too few retries"

#### 2. `copy_ms` growth directly hurts `cap_fps`

Receiver logs showed a recurring pattern:

- when `copy_ms` becomes larger
- `cap_fps` falls correspondingly

This is expected because capture throughput is bounded by:

- grab time
- copy time
- dedup time

So receiver throughput analysis must treat `copy_ms` as a first-class capture
cost, not just a secondary metric.

Implication:

- any future decode-cost analysis must separately account for `grab_ms`,
  `copy_ms`, and `dedup_ms`
- any capture optimization on macOS may matter as much as decode optimization
  once decode is no longer the dominant bottleneck

#### 3. We need a rendering strategy that preserves a global uniform module pitch

The current sender behavior exposed an important design flaw:

- reducing `module-grid` does not automatically improve readability enough
- because the visible symbol area is not being managed with the right policy

One attempted fix was to "fill more of the available pixel budget" by allowing
non-uniform cell widths/heights. That approach was wrong for this system:

- it preserved total occupied area better on paper
- but it broke the assumption of uniform module pitch
- and made live decoding worse

So the correct requirement is now explicit:

> We need a rendering strategy that keeps a single global uniform module pitch.

That means:

- every module in a frame should still have the same pixel size
- the sender should not distribute leftover pixels by varying cell widths across
  the frame
- any future "better use of 1920x1080" strategy must preserve this uniformity

#### 4. `module-grid` is not "fixed presets only", but it is not arbitrary either

The current implementation accepts continuous `module-grid` values on both the
sender and receiver side. There is no hardcoded whitelist of allowed grid
shapes.

However, real screen decode is not expected to be equally stable for every
possible grid:

- the geometry must still fit a good uniform module pitch on the target display
- the overall frame aspect ratio should stay reasonably aligned with the screen
  aspect ratio
- very tall or very wide grids can shrink the limiting module pitch even if the
  total symbol count looks acceptable on paper

Example on a 1920x1080 display:

- `224x136` stays near the working aspect band and can keep a `6 px/module`
  integer pitch
- `240x144` also stays in that band and can keep a `6 px/module` pitch
- `192x160` becomes too tall and drops to about `5 px/module`, which is much
  less forgiving for gray4

So the right engineering model is:

- `module-grid` is not limited to a few official presets
- but only a subset of grids is likely to be practically stable on a given
  display

One more practical warning:

- "smaller grid should always be more robust" is only a design goal, not a
  property of the current implementation
- some much smaller grids were observed to decode worse or almost not at all
- that means geometry, placement, and current sampling behavior still interact
  in non-monotonic ways

#### 5. Sender chunk sizing should be ratio-driven

The sender previously kept two controls alive at the same time:

- `chunk-size`
- `chunk-fill-ratio`

That is the wrong abstraction for the current stage.

The effective chunk size should be derived from:

- frame payload capacity
- fill ratio

and not from a hidden default byte count such as `2048`.

Correct principle:

- keep `chunk-fill-ratio`
- compute `effective_chunk_size = floor(frame_payload_cap * ratio)` with
  reasonable lower/upper clamps
- if an explicit byte-size override still exists internally for tests, it
  should be treated only as an optional clamp, not as the primary user-facing
  control

### Viable Strategy For `module-grid`

We should treat grid selection as a constrained search problem, not as an
arbitrary free parameter.

Recommended strategy:

1. Fix the real screen budget first
   - for example 1920x1080

2. Compute the uniform module pitch implied by each candidate grid
   - using the full frame geometry, not just payload grid size

3. Prefer grids that:
   - keep a larger integer pitch
   - stay near the display aspect ratio
   - avoid pathological tall/narrow or wide/short layouts

4. Build a "stable band" instead of a single magic grid
   - for example several candidate grids that all preserve an acceptable module
     pitch on 1920x1080

5. Benchmark only inside that band
   - instead of spending time on obviously geometry-hostile grids

This is compatible with the earlier rendering conclusion:

- future sender work should still preserve a global uniform module pitch
- but grid choice itself should also respect the screen geometry

### What Was Reverted

The exact-fill rasterization experiment was reverted.

Reason:

- it improved pixel-budget utilization in theory
- but degraded real decode behavior in practice

We are back on the safer integer, uniform-pitch rendering path.

### Decoder Situation

We also confirmed a separate decoder issue:

- recent header/bad-frame experiments added significant decode overhead
- but produced little practical benefit on the remaining hard frames

So tomorrow's work should start with cost analysis, not more speculative decode
fallbacks.

### Persistent Bad Chunks

Another important finding is that a small set of chunks can remain undecodable
even at the default module grid and even when ECC level changes.

This strongly suggests that the current remaining failures are not explained by:

- only using an aggressive grid
- only using too little ECC
- only queue pressure or worker count

Instead, the remaining bad cases are likely content-specific:

- certain chunk payloads appear to produce especially fragile visual patterns
- neighboring chunks can decode while one specific chunk fails repeatedly
- the same missing chunks can persist in both live capture and captured replay

That points toward a likely root cause:

- some specific symbol or mask patterns are unusually hard to decode under the
  current gray4 sampling and display chain

So the next debugging direction should explicitly treat these as possible
pattern-driven failures rather than only throughput or ECC problems.

Another now-validated implication:

- if the same chunk is rendered with the same visual pattern on every epoch,
  static screen/capture geometry can make it fail in the same way forever
- sender-side diversity, even in a very low-cost form such as mask diversity,
  can therefore be a real robustness lever for gray4

### Recommended Next Steps

#### A. Do a full decode cost breakdown

We need a concrete accounting of gray4 decode cost:

- base locator path
- axis-aligned fast path
- header fallback
- payload fallback
- any remaining extra sampling logic

Output should show:

- average cost
- tail cost
- hit rate
- actual recovery benefit

Anything expensive with little win should be removed or gated much more tightly.

#### B. Design a new uniform-pitch rendering policy

This should be handled at the sender/rendering layer.

The goal is:

- keep the module pitch globally uniform
- use screen pixels more intentionally
- avoid the current situation where changing grid count does not produce enough
  practical readability difference

Likely direction:

- choose a single pitch from the available 1920x1080 budget
- center the symbol field
- allow larger margins if needed
- but never vary module width/height within one frame

#### C. Continue treating persistent bad frames as first-class test cases

The hard frames/chunks we already isolated should remain regression targets.

We should keep using:

- captured replay inputs
- sender-vs-captured comparisons
- specific bad chunk/frame windows

because aggregate metrics alone will hide these failures.

#### D. Investigate persistent bad chunks as pattern failures

The next concrete debugging step should focus on the fixed missing chunks.

Questions to answer:

- do these chunks share unusual symbol distributions?
- do they correlate with a particular mask interaction?
- do they create locally low-contrast or high-frequency patterns after gray4
  rendering?
- do they stay bad even when all throughput conditions are relaxed?

If the answer remains yes, then the problem should be treated as a
pattern-robustness problem, not an ECC problem.

### Bottom Line

Tonight's useful conclusions are:

1. Even loose gray4 settings can still leave a few frames undecodable.
2. When `copy_ms` rises, `cap_fps` drops, so capture cost is part of the real
   throughput ceiling.
3. Future rendering work must preserve a global uniform module pitch.
4. `module-grid` support is continuous in code, but only a geometry-friendly
   subset is likely to be stable on a real 1920x1080 screen.
5. Some persistent bad chunks now look more like pattern-driven decode failures
   than throughput or ECC failures.
6. Before closing this phase, we need a complete performance analysis that
   breaks down the costs and then optimizes them systematically.

That is the correct starting point for tomorrow.
