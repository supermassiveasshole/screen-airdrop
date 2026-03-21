# Gray4 Layered Full ECC Design

## Status

This document proposes the next-stage protocol built on top of the current `gray4` baseline.

The key decision is:

- `layered` should remain a distinct protocol implementation
- but it should be explicitly designed as a structural extension and refactor of `gray4`
- the goal of this stage is to introduce:
  - full ECC
  - explicit control/data layering
  - better startup behavior
  - reuse of the proven gray4 modulation/calibration/diversity lessons

In other words:

- current `gray4` = working single-layer baseline
- next `layered` = gray4-derived layered protocol with full ECC

This keeps protocol evolution clear while preserving the current `gray4` code as a stable baseline.


## Goals

This stage must solve four problems together:

1. Header/control information must be easier to recover than it is today.
2. Payload must use real ECC, not repetition plus discard.
3. Startup must become lighter and more purposeful.
4. The new structure must increase usable robustness without destroying the current `gray4` baseline.


## Non-Goals

This stage does not attempt to:

- introduce OGRB or cross-frame recovery semantics
- redesign locator geometry from scratch
- maximize raw payload density at any cost
- rely on heavy decoder-side brute-force search

OGRB remains a later stage built on top of this structure.


## Design Summary

The new `gray4` frame is split into three conceptual layers:

1. `locator/timing shell`
2. `bootstrap control layer`
3. `coded body layer`

These are not three separate protocols. They are three roles inside the next `gray4` frame design.


## 1. Locator/Timing Shell

This outer shell keeps the existing responsibilities:

- acquisition
- alignment
- sampling stability
- frame boundary detection

Constraints:

- keep geometry simple
- avoid overloading this shell with payload semantics
- continue to support current ROI lock/reuse behavior

This layer should remain visually robust and cheap to detect.


## 2. Bootstrap Control Layer

This is the replacement for the current overgrown header path.

Its purpose is to carry only the minimum information required to decode the rest of the frame.

### Requirements

- must be more robust than the gray4 body
- should use coarser representation than body data
- should support its own short ECC and CRC
- should be physically distinct from body data

### Recommended physical treatment

- binary or near-binary representation
- larger effective modules than body modules
- fixed placement
- stable mask strategy

Current vNext.1 implementation note:

- the control band remains physically separate from the body
- each `3x2` control cell now carries one `2-bit` template symbol rather than a single thresholded bit
- the bootstrap band is `4` control rows plus `1` isolation row
- reference cells are template references, not just dark/light threshold anchors

### Bootstrap contents

Only fields required to enter body decode should live here.

Recommended fields:

- protocol/version id
- frame type
- short session or generation identity
- body profile id
- body payload length
- body realization seed / mask seed
- bootstrap CRC

Current vNext.1 implementation note:

- `body ECC profile id` is no longer transmitted separately on the wire
- a compact `body profile wire id` maps deterministically to the internal body ECC profile
- `coded symbol length` is derived from `payload_len + body_profile`

Possible optional fields:

- calibration profile id
- coarse frame sequence id

The bootstrap layer should not carry the entire old header.


## 3. Coded Body Layer

This layer contains:

- the remaining non-bootstrap header fields
- payload bytes
- body CRC

The key design decision is:

- treat this as one coded object
- do not keep a large independent "payload plus old header" split

This is the main place where `layered` improves both robustness and usable payload efficiency.


## ECC Strategy

The system uses two ECC domains, not one.

### Bootstrap ECC

Purpose:

- guarantee reliable entry into body decode

Properties:

- short block code
- strong relative protection
- small absolute footprint

Candidate families:

- short BCH
- short Reed-Solomon
- SECDED-style short codes if the bootstrap remains very small

Selection criteria:

- low implementation risk
- good correction capability for a short message
- clean failure semantics


### Body ECC

Purpose:

- correct payload/body errors before CRC validation

Properties:

- real block ECC
- much stronger than current repetition scheme
- should be defined in terms of clear correction capability

Recommended first candidate:

- Reed-Solomon over bytes

Reasons:

- current gray4 receiver already reconstructs bytes
- integration cost is lower than soft-decision codes
- correction capability is easy to reason about
- later erasure support can be added without redesigning the frame again


### CRC Semantics

CRC remains in the design, but only as final integrity validation.

Rules:

- bootstrap ECC decode first, then bootstrap CRC
- body ECC decode first, then body CRC
- discard only if ECC output still fails CRC

This replaces the current repetition-plus-discard behavior.


## Layering Semantics

In this stage, `layered` means:

- control and data are intentionally separated
- not all information is given the same modulation, geometry, or protection strength
- the body is decoded only after bootstrap succeeds

This stage does not yet mean:

- cross-frame bootstrap merging
- generation-level reconstruction
- OGRB window semantics

Those remain later additions.


## Calibration Strategy

Calibration remains part of gray4, but is subordinate to startup and decode quality.

### Keep

- sync-based calibration
- calibration-by-mask or calibration-by-profile caching

### Change

- keep startup lighter than the current heavy preamble
- calibration should support body decoding, not dominate startup time

Recommended direction:

- a small sync/calibration burst up front
- bootstrap burst after calibration
- then enter body data quickly

Calibration should improve decoding, not become a second payloadless protocol.


## Mask and Diversity Strategy

Mask and diversity remain important, but now have separate roles by layer.

### Bootstrap

- prefer stability over diversity
- use a small, predictable set of realizations
- do not optimize aggressively for payload-like variation

### Body

- continue to use diversity
- preserve sender-side realization changes across retries/epochs
- retain compatibility with future OGRB or sliding-window redundancy

This keeps the earlier gray4 insight:

- repeated transmission without changed visual realization has low recovery value


## Startup Strategy

Startup should be explicitly simplified relative to the current baseline.

Recommended startup order:

1. short sync/calibration burst
2. short bootstrap/control burst
3. body data as early as possible

Startup should no longer rely on:

- long sync preambles
- repeated calibration responsibilities in later control bursts
- heavy overlap between acquisition, calibration, and control repetition


## Relationship To Gray4

`layered` should be implemented as a separate protocol module, not as a destructive rewrite of `gray4`.

This is intentional.

Reasons:

- preserve a known working baseline
- make A/B comparison between `gray4` and `layered` straightforward
- avoid destabilizing current gray4 behavior during ECC redesign
- follow open-closed design principles:
  - extend with a new protocol
  - avoid rewriting the existing protocol in place

So the intended relationship is:

- `gray4` remains available and stable
- `layered` reuses gray4 lessons, geometry ideas, calibration strategy, and robustness learnings
- `layered` is the new place where bootstrap/body separation and full ECC are introduced


## Migration From Current Gray4

Current gray4 has these useful assets:

- locator/timing shell
- sender-side diversity
- header-aware mask selection experience
- calibration frames
- lock/reuse ROI behavior
- better observability

The next design should reuse those lessons, not discard them.

### Keep from current baseline

- calibration as a real mechanism
- startup observability
- lock/reuse decode behavior
- sender-side diversity for body data

### Replace inside layered

- large mixed header path
- repetition-as-ECC
- payload CRC mismatch as the first real recovery gate


## Proposed First Implementation Cut

The first implementation of layered should be:

- bootstrap layer:
  - binary or coarse control region
  - short ECC
  - bootstrap CRC

- body layer:
  - gray4 coded body
  - Reed-Solomon over bytes
  - body CRC

- startup:
  - reduced sync/calibration burst
  - short bootstrap burst
  - early body transmission

This is the recommended first milestone because it changes the structure enough to matter, without yet requiring OGRB and without rewriting the current gray4 implementation.


## Open Questions

These questions should be resolved before implementation locks in:

1. Which exact bootstrap fields are truly required before body decode?
2. Should the bootstrap be fully binary, or just coarser/larger than body gray4?
3. What is the first body ECC profile:
   - single RS profile
   - or a small set of RS strength profiles?
4. Should the remaining old-header fields be fully absorbed into the coded body, or should a small secondary control segment remain?
5. How small can startup become while preserving acquisition reliability?


## Recommendation

Proceed with this stage as:

- `layered protocol built from gray4 baseline learnings`

Do not rewrite the current `gray4` implementation in place.

Instead:

- keep `gray4` as the stable baseline
- build `layered` as the new full-ECC protocol
- reuse gray4 knowledge, but keep protocol boundaries explicit

Use the next implementation phase to:

1. define bootstrap fields
2. define body ECC framing
3. implement bootstrap/body split
4. keep calibration and diversity where they are useful
5. prepare the structure for later OGRB, without implementing OGRB yet
