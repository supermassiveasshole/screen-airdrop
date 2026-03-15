# Screen-Airdrop Throughput Optimization Plan

> Role: this is the execution roadmap.
>
> It answers:
> - what stage we are in now
> - what workstreams are active
> - what is blocked, deferred, or completed
> - what the next concrete milestones are
>
> It does **not** redefine architecture or normative boundaries. Those live in
> [throughput_optimization_strategy.md](./throughput_optimization_strategy.md).

## Current Stage

Current program state:
- `Phase 0` complete: protocol interface decoupling
- `Phase 1` complete: `compact` validated
- `Phase 2` partially validated: `gray4` payload path is viable
- `Phase 3` is now the next mainline target: `layered`

Current working judgment:
- `gray4` is no longer blocked on payload viability
- the dominant remaining blur failure is `control/header`, not payload
- the original `layered` target remains dual-purpose:
  - increase control-plane robustness
  - preserve or improve usable payload density under the same screen budget
- therefore the next architectural candidate remains `layered`, but it should be treated as the next single-frame capacity experiment, not as a robustness-only detour

## Active Workstreams

### Workstream A: Gray4 Validation Closure

Purpose:
- finish the minimum validation needed to stop treating `gray4` as speculative

Already achieved:
- clean replay restore succeeds
- high-throughput local screen runs exceed prior `compact` baseline
- controlled perturbation bench exists
- controlled blur shows first failure is `bad v3 magic`, not payload CRC
- sender-side mask diversity has been validated as a low-cost mitigation for
  fixed bad chunks in static screen/capture conditions

Exit criteria:
- `gray4` is documented as payload-viable but control-limited
- no further large `gray4`-specific feature work is required before `layered`

Out of scope:
- turning `gray4` into a long-term solution for control-plane robustness

### Workstream B: Control Decode Primitive

Purpose:
- extract reusable receiver-side control/header decoding logic that later protocols can reuse

Current status:
- control/header decode has been separated from payload demodulation
- gray4 already uses a dedicated control decode primitive
- primitive now supports threshold candidates and raw-sample voting

Next target:
- freeze the primitive interface unless `layered` requires a clearly better abstraction

Exit criteria:
- `layered` can reuse this primitive without needing another decoder rewrite

### Workstream C: Layered Protocol Minimum Prototype

Purpose:
- prepare and implement the first protocol where control plane and data plane are explicitly separated, in line with the original Phase 3 plan

Why now:
- this is the first phase that directly addresses the currently observed failure mode
- it is also the first phase intended to improve payload efficiency by separating robust control costs from the main data budget

Minimum prototype requirements:
- robust binary control plane
- denser payload plane
- explicit physical separation between control and data areas
- no OGRB dependency
- no adaptive sender logic

Exit criteria:
- synthetic roundtrip works
- replay benchmark demonstrates that control/header survives blur better than `gray4`
- replay or screen benchmarks show that `layered` does not regress usable payload efficiency relative to `gray4`
- benchmark reports clearly distinguish `control-limited` vs `data-limited` failure

### Workstream D: Benchmark and Diagnostics

Purpose:
- keep a stable measurement surface while protocol work continues

Current assets:
- replay benchmarks
- screen benchmarks
- debug snapshot analyzer
- debug snapshot comparison tool
- perturbation benchmark for controlled blur/degradation

Required maintenance:
- every protocol phase must keep producing comparable outputs
- every blur/control failure must stay attributable to `locator`, `control`, or `data`

## Execution Order

The current recommended order is:

1. Close `gray4` as a payload-valid but control-limited phase.
2. Stop spending major effort on `gray4`-only header hacks that effectively turn it into hidden `layered`.
3. Re-enter the original Phase 3 question: can layered header/data separation improve effective capacity and robustness together?
4. Reuse current control-plane schema and control decode primitives where possible.
5. Only after `layered` single-frame value is clear, resume `erasure` / `OGRB` work.

## Immediate Milestones

### Milestone 1: Gray4 Closure

Definition of done:
- strategy and plan both reflect that `gray4` is no longer the mainline target for control robustness
- `gray4` remains available as a benchmarked payload-density protocol

### Milestone 2: Layered Spec Skeleton

Definition of done:
- minimal frame layout is specified
- coarse control plane responsibilities are defined
- data plane responsibilities are defined
- compatibility boundary with existing control-plane schema is documented
- the spec preserves the original expectation that `layered` should pursue payload efficiency gains, not robustness alone

### Milestone 3: Layered Prototype

Definition of done:
- sender can emit layered frames
- receiver can decode coarse control plane before touching payload
- replay and perturbation benchmarks can compare `gray4` vs `layered`

### Milestone 4: Layered Evaluation Gate

Definition of done:
- under controlled blur, `layered` reduces control/header failure rate relative to `gray4`
- if it does not, redesign control layout before moving upward to `erasure` or `OGRB`

## Deferred Items

Deferred until after `layered` prototype:
- OGRB sender/receiver integration
- generation scheduling redesign
- adaptive sender policy
- capture backend rewrite
- locator redesign
- pilot-grid experiments

Deferred because:
- they do not solve the current first failure mode
- they would increase variable count before control-plane survival is settled

## Completed Work

Completed:
- protocol interface decoupling
- `basic` compatibility preservation
- `compact` implementation and validation
- `gray4` payload modulation path
- replay/debug observability chain
- control-plane schema groundwork
- receiver-side control decode primitive extraction

## Working Rules

For current execution:
- do not let `plan` become a second strategy document
- do not merge long-term architectural arguments here; reference `strategy`
- every new task should map to one active workstream and one milestone
- if a task does not advance control survival, payload viability, or benchmark clarity, it is probably not current priority
