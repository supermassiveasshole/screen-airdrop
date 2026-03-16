# Screen-Airdrop — Scope, Vision, and Engineering Evolution Plan

## 1. Project Vision

Screen‑Airdrop aims to build a **high‑throughput visual communication system** capable of transferring arbitrary binary data through an unreliable visual channel:

```
screen → compositor → remote desktop → compression → capture → decoder
```

The long‑term goal is to evolve from a simple visual demo into a **full visual communication stack**, similar in spirit to traditional communication systems but implemented on top of a graphics/display pipeline.

The system will progressively combine:

- protocol engineering
- visual modulation
- adaptive decoding
- diversity and redundancy
- GPU‑accelerated decoding
- optional ML perception and control

A key principle is **progressive engineering**: the protocol evolves step‑by‑step, increasing robustness and sophistication over time rather than jumping directly to complex ML or opaque solutions.

---

# 2. Current Experimental Insight

Recent experiments show several consistent observations:

### Sender correctness

Sender‑generated frames are correct.

### Channel distortion

Errors originate from the **display → capture pipeline**, which introduces:

- blur
- brightness shift
- compression artifacts
- sampling error

These distortions occasionally push frames beyond the **decoding margin**.

### Failure types

Observed failures include:

- `bad magic` → header decode failure
- `payload crc mismatch` → payload symbol corruption

### Realization sensitivity

Mask‑divergence experiments demonstrate:

- the same payload may succeed under a different visual realization
- failures are **pattern‑dependent**, not purely random noise

This implies robustness must come from **protocol evolution and diversity**, not simply stronger ECC.

---

# 3. Core Design Philosophy

## 3.1 Layered architecture

The system should be decomposed into layers:

```
visual modulation
symbol detection
frame protocol
redundancy protocol
session protocol
```

Each layer evolves independently.

## 3.2 Margin‑first design

Improving **symbol reliability** is usually more effective than increasing ECC strength.

Focus first on:

- decoding margin
- calibration
- adaptive thresholds

before increasing redundancy.

## 3.3 Progressive protocol engineering

The system evolves through stages of increasing sophistication:

1. baseline frame protocol
2. diversity‑aware frames
3. redundancy protocols (OGRB)
4. stateful transmission
5. accelerated decoding
6. ML augmentation

## 3.4 ML as augmentation, not foundation

Machine learning should enhance **perception and adaptation**, not replace the entire protocol.

Deterministic protocols remain the backbone of the system.

---

# 4. System Architecture

## Sender

Components:

- frame scheduler
- payload encoder
- mask generator
- visual renderer

Responsibilities:

- encode data into visual frames
- generate diversity realizations
- schedule redundancy and updates

## Channel

Uncontrolled environment including:

- display hardware
- compositor
- remote desktop compression
- capture pipeline

## Receiver

Components:

- capture pipeline
- ROI detection
- GPU preprocessing
- symbol detection
- header decoding
- payload reconstruction

---

# 5. Protocol Evolution Roadmap

The system evolves through **sequential engineering stages**.

Each stage builds on the previous one.

---

# Phase 0 — Physical / Symbol Robustness (Current Stage)

The current priority is **single‑frame robustness**.

Focus areas include:

- gray4 robustness improvements
- threshold stability
- header reliability
- decoding margin analysis

Key mechanisms:

- adaptive thresholds
- calibration
- symbol confidence

Goal:

```
make single‑frame decoding stable enough
before introducing complex protocols
```

---

# Phase 1 — Diversity‑Aware Frames

Observation:

Failures often depend on **specific visual realizations**.

Therefore the system introduces controlled diversity.

Techniques include:

- mask divergence
- symbol permutation
- spatial tile permutation

Effect:

```
same payload
→ multiple visual realizations
→ higher probability of successful decoding
```

This stage formalizes the concept of **realization diversity**.

---

# Phase 2 — OGRB Redundancy Protocol

OGRB introduces **group‑based redundancy across frames**.

Instead of treating frames independently, frames belong to a group that collectively reconstructs the payload.

Basic concept:

```
chunk
→ multiple overlapping frames
→ receiver merges recovered symbols
```

Key properties:

- partial frame success becomes useful
- erasures can be tolerated

### Diversity‑integrated OGRB

Diversity mechanisms integrate directly into OGRB:

- mask‑divergent realizations
- spatial permutation
- symbol‑level diversity

This transforms OGRB into a **diversity‑aware group reconstruction protocol**.

---

# Phase 3 — Channel‑Aware Decoding

Receiver decoding becomes adaptive.

Key mechanisms:

## Pilot calibration

Reference symbols estimate:

- brightness offset
- contrast compression
- gray‑level centers

## Adaptive thresholds

Receiver dynamically estimates gray4 boundaries.

## Confidence scoring

Symbols output confidence values.

Low‑confidence symbols become **erasures** rather than incorrect bits.

This greatly improves ECC performance.

---

# Phase 4 — Content Robustness

Payload statistics may produce visually fragile patterns.

Techniques include:

### Whitening

Scramble payload bits to avoid pathological visual patterns.

### Interleaving

Spread payload bits spatially to mitigate localized damage.

### Tile diversity

Alter spatial placement of symbols across frames.

These techniques reduce **pattern‑dependent failures**.

---

# Phase 5 — Incremental Rendering Protocol

Sender throughput eventually becomes a bottleneck.

Inspired by:

- video codecs
- remote desktop protocols

Introduce a **stateful transmission model**:

```
persistent canvas
+ tile updates
```

Frame types:

- keyframes (full canvas)
- delta frames (tile updates)

Benefits:

- reduced rendering cost
- higher effective frame rate
- selective retransmission

---

# Phase 6 — GPU‑Accelerated Decoding

Receiver throughput may become limiting.

GPU acceleration enables:

- module sampling
- filtering
- histogram computation
- symbol classification

This allows larger grids and higher throughput.

---

# Phase 7 — ML‑Assisted Decoding

ML enhances perception components where deterministic decoding is fragile.

Examples:

### Symbol classifier

```
patch → CNN → gray4 probability
```

### Header classifier

```
header patch → bit predictions
```

Protocol structure remains unchanged.

---

# Phase 8 — ML‑Driven Protocol (Research Direction)

ML may eventually influence protocol decisions.

Possible applications:

- selecting mask policies
- choosing redundancy strength
- adapting modulation schemes
- dynamic tile scheduling

This represents a **learned control layer** above the deterministic protocol.

---

# 6. Metrics

Key performance metrics:

- header decode success rate
- payload CRC success rate
- frame success probability
- throughput (KB/s)
- frames required per chunk

---

# 7. Long‑Term Vision

If the roadmap succeeds, Screen‑Airdrop becomes a **general visual communication stack** combining:

- diversity‑aware protocols
- adaptive decoding
- GPU acceleration
- optional ML augmentation

Potential applications include:

- air‑gapped data transfer
- visual networking experiments
- robotics communication
- AR/VR device pairing

