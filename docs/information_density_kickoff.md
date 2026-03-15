# Screen-Airdrop Kickoff

> Role: this is the near-term worklist.
>
> It exists to answer:
> - what should be implemented next
> - in what order
> - what each task must produce
>
> Strategy is in [throughput_optimization_strategy.md](./throughput_optimization_strategy.md).
> Roadmap is in [throughput_optimization_plan.md](./throughput_optimization_plan.md).

## Current Objective

Current objective:
- prepare the next single-frame experiment so that `layered` can be evaluated against its original goals

Reason:
- `gray4` has already established payload viability
- the dominant remaining failure is control/header survival under blur
- the original plan for `layered` was not robustness alone; it was header/data stratification to improve both robustness and effective payload capacity

## Kickoff Sequence

### Step 1: Write The Minimum Layered Spec

Deliverable:
- a compact protocol note or spec draft for the minimum `layered` frame

Must define:
- control area position
- data area position
- coarse control fields
- payload area assumptions
- which existing control-plane fields remain shared

Must not include yet:
- OGRB integration
- sender adaptation
- cross-generation recovery logic

### Step 2: Add Layered Protocol Skeleton

Deliverable:
- sender and receiver protocol adapters for `layered`

Minimum behavior:
- encoder can render a frame with separate control and data areas
- decoder can read coarse control before payload
- protocol can participate in replay tests

### Step 3: Reuse Control Decode Primitive

Deliverable:
- `layered` control path uses the extracted control decode helper rather than re-implementing header logic

Goal:
- keep control robustness work in one reusable place

### Step 4: Build Minimum Replay Validation

Deliverable:
- synthetic roundtrip
- replay roundtrip
- at least one blur/perturbation comparison against `gray4`

Required output:
- `control/header` failure rate
- `data` failure rate
- locator failure rate

### Step 5: Evaluate Go / No-Go

Questions:
- does layered reduce control-plane failure before payload failure?
- does layered preserve enough payload density to remain worthwhile?
- does layered keep its robustness win without collapsing the payload budget?
- does layered still answer the original "single-frame capacity" question better than continuing to patch `gray4`?

If yes:
- continue layered refinement

If no:
- redesign control layout before touching OGRB

## Current Task List

Priority 1:
- define the minimum `layered` frame layout
- define coarse header fields and responsibilities
- define compatibility boundary with current control-plane schema

Priority 2:
- add encoder/decoder skeletons
- wire sender/receiver CLI and pipeline support
- add replay tests

Priority 3:
- add perturbation benchmark cases for layered vs gray4
- record whether first failure is control or data

## Explicit Non-Goals

Not part of this kickoff:
- rewriting locator
- replacing capture backend
- implementing full OGRB flow
- adding sender-side adaptive scheduling
- redesigning the entire control-plane schema from scratch

## Completion Condition

This kickoff is complete when:
- a minimum `layered` protocol exists in code
- it can be benchmarked in replay
- it produces evidence about control survivability under blur
- the project can decide whether `layered` should become the new mainline physical-layer direction
