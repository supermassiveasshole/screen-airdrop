# Screen-Airdrop Architecture Refactor Plan

Status: Phase 1 complete; compatibility layer retired; real systematic generation model complete; boundary maintenance complete; OGRB feature work not started  
Scope: sender, receiver, common package structure  
Primary goals:

1. improve cohesion and reduce coupling in the existing codebase
2. prepare the codebase for OGRB and erasure coding without another structural rewrite
3. preserve current live and replay behavior while moving code into cleaner module boundaries

Current phase boundary:

1. this document governs structural reorganization and module-boundary cleanup
2. it does not imply that OGRB transport semantics, coded units, or schedulers are being implemented in the same step
3. information/scheduling package work in the current phase is limited to architecture scaffolding and systematic-only model cleanup

Current status summary:

1. top-level compatibility modules have been removed, and subdomain packages are now the only supported internal implementation paths
2. package entrypoint export surfaces have been narrowed to stable facades rather than convenience re-export dumps
3. factory modules are now the intended high-level implementation-selection boundary for transport, pipeline, and reporting, and duplicate factory surfaces have been retired
4. the systematic-only information/scheduling skeleton and real generation-scoped systematic model are in place
5. the codebase is now in structural maintenance mode: future cleanup should be small boundary-preserving adjustments rather than new package migrations
6. the final boundary-maintenance pass has removed remaining redundant wrappers and duplicate implementation-selection edges
7. this document is still governing structure and boundary cleanup only, not OGRB feature implementation

Current batch goals:

1. preserve the sealed package boundaries and stable facades
2. avoid re-introducing convenience re-export surfaces, duplicate factories, or top-level implementation leakage
3. keep `application -> pipeline -> runtime/transport/reporting/information` dependency direction stable
4. avoid any wire-format, scheduler-policy, coded-unit, or solver changes while doing so

## 1. Why Refactor

The current codebase is functional, but many modules are organized by historical growth rather than by stable responsibility boundaries.

The main structural problems are:

1. `sender/` and `receiver/` top-level directories contain too many concrete implementation files.
2. protocol, scheduling, transport, runtime, ROI, and reporting responsibilities are partially mixed.
3. current protocol abstractions are transport-centric and are not sufficient for the future OGRB information/scheduling model.
4. replay/live/runtime/reporting boundaries are not always clean, which makes future changes riskier than necessary.

This refactor is not a feature rewrite. It is a structural cleanup so that future work can be added without pushing more complexity into the current top-level files.

## 2. Design Principles

The refactor should follow these rules.

### 2.1 Organize by domain, not by historical file placement

Top-level packages should represent durable subdomains:

1. `information`
2. `scheduling`
3. `transport`
4. `pipeline`
5. `runtime`
6. `reporting`
7. `roi`
8. `locator`
9. `application`

Current status:

1. `common/__init__.py`, `sender/__init__.py`, and `receiver/__init__.py` now act as domain-entry packages rather than empty placeholders.
2. Their primary role is to expose stable subpackage boundaries for the repository's implementation surface.

### 2.2 Preserve strict layer boundaries

The target architecture aligns with the OGRB specification:

1. Information layer: what is transmitted
2. Scheduling layer: when it is transmitted
3. Visual transport layer: how it is rendered and decoded

Current implementations such as `basic`, `compact`, `gray4`, and `layered` belong to the transport layer, not the information layer.

### 2.3 Core subsystems must be pluggable

Several parts of the codebase must be treated as replaceable modules rather than singleton implementations.

The most important plugin points are:

1. `locator`
2. `pipeline`
3. `reporting`

That means:

1. each of these domains should have a stable interface boundary
2. factories or registries should choose implementations
3. high-level orchestration should depend on those interfaces, not concrete implementations
4. registration-style extension points should exist where that improves testing and future injection

`basic locator`, `live pipeline`, and the current console/json reporting flow are only the first implementations. They must not define the architecture as if they were the only possible variants.

### 2.4 Pipeline must be distinct from runtime

Pipeline implementations are not the same thing as runtime infrastructure.

For the receiver in particular:

1. `live_runtime` is a decode pipeline implementation
2. `replay_pipeline` is another decode pipeline implementation
3. future lower-cost or alternative pipelines must be able to coexist beside them

Therefore:

1. `pipeline/` should contain high-level decode pipeline implementations
2. `runtime/` should contain reusable infrastructure used by those pipelines

### 2.5 Runtime must not own protocol semantics

Live/replay runtime code should manage:

1. capture
2. shared memory
3. process/thread orchestration
4. queueing
5. timing
6. reporting hooks

Runtime code should not need to understand layered bootstrap fields, body profile semantics, or future coded-equation semantics.

### 2.6 Reporting must observe, not control

Reporting code should consume normalized events and summaries. It should not depend on protocol-private object layouts or worker-private metadata conventions.

### 2.7 Replay should mirror live semantics

Replay exists to debug and validate live behavior. Replay should reuse the same runtime and locator semantics wherever practical, and only add diagnostics as side-band information.

## 3. Target Package Structure

## 3.1 `common/`

Target structure:

```text
common/
  information/
  scheduling/
  transport/
  control_plane/
  manifest.py
  packing.py
  errors.py
```

### Responsibilities

`common/information/`

1. transmission-unit models
2. generation identifiers
3. future coded-equation metadata
4. future erasure-coding primitives shared by sender and receiver

`common/scheduling/`

1. scheduling interfaces
2. OGRB policy definitions
3. redundancy and revisit policy contracts

`common/transport/`

1. transport-level frame/header structures
2. transport layout metadata
3. protocol-specific shared constants for `basic`, `compact`, `gray4`, `layered`

### Immediate migration targets

These files should ultimately move under `common/transport/`:

1. [protocol_basic.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/common/transport/protocol_basic.py)
2. [protocol_gray4.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/common/transport/protocol_gray4.py)
3. [protocol_layered.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/common/transport/protocol_layered.py)
4. [layout_basic.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/common/transport/layout_basic.py)
5. [layout_compact.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/common/transport/layout_compact.py)

Current status:

1. Real transport implementations already live under `common/transport/`.
2. Source-path imports have been moved to `screen_airdrop.common.transport.*`.
3. `common/transport/*` is now the only supported internal transport path.
4. `common/information/` and `common/scheduling/` now exist as stable domain namespaces.
5. The current refactor phase has introduced systematic-only information and scheduling skeletons without changing transport wire format.
6. The bridge-phase `generation_id = 0` shortcut is being replaced by a real multi-generation systematic model.

## 3.2 `sender/`

Target structure:

```text
sender/
  cli/
  application/
  information/
  scheduling/
  transport/
  render/
```

### Responsibilities

`sender/cli/`

1. CLI entrypoints
2. argument parsing
3. top-level user-facing startup behavior

`sender/application/`

1. sender orchestration
2. session construction
3. manifest and payload preparation
4. top-level frame-stream assembly

`sender/information/`

1. convert packed source bytes into generations
2. build future `TransmissionUnit` streams
3. future systematic/coded-unit construction

`sender/scheduling/`

1. schedule control/data emission
2. epoch/bootstrap sequencing
3. current broadcast policy
4. future OGRB scheduling

`sender/transport/`

1. protocol-specific visual encoders
2. transport adapters
3. protocol-specific layout/profile helpers

`sender/render/`

1. frame presentation
2. CV2 or other rendering backends

## 3.3 `receiver/`

Target structure:

```text
receiver/
  cli/
  application/
  roi/
  locator/
  transport/
  information/
  pipeline/
  runtime/
  reporting/
```

### Responsibilities

`receiver/cli/`

1. CLI entrypoints
2. argument parsing
3. top-level startup and shutdown orchestration

`receiver/application/`

1. replay source orchestration
2. restore and output handling
3. high-level pipeline wiring

`receiver/roi/`

1. ROI selection
2. ROI policy
3. ROI setup
4. ROI persistence
5. ROI transforms

`receiver/locator/`

1. frame locating
2. locator state machine
3. geometry reuse logic
4. locator diagnostics
5. pluggable locator implementations and factory wiring

`receiver/transport/`

1. transport-specific single-frame decode
2. transport adapters
3. transport observability helpers
4. protocol-specific visual geometry handling

`receiver/information/`

1. generation state
2. deduplication at semantic-unit level
3. future systematic/coded ingestion
4. future erasure decoding
5. assembly logic

`receiver/pipeline/`

1. high-level decode pipeline implementations
2. live fixed-slot / high-throughput pipeline
3. replay pipeline
4. future lower-cost or alternative pipeline strategies
5. pluggable pipeline selection and orchestration boundary

`receiver/runtime/`

1. screen capture
2. workers and shared-memory infrastructure
3. slots/shared memory
4. inter-process coordination
5. runtime timing and counters

`receiver/reporting/`

1. summary collection
2. protocol collectors
3. stats collection
4. report formatting
5. final report generation
6. pluggable reporters / sinks / collectors

## 3.4 Pluggable subsystem boundaries

The following packages should be explicitly designed as extension points.

### `receiver/locator/`

This package should support multiple locator implementations behind a stable interface.

Expected internal roles:

1. `interfaces.py`
2. `factory.py`
3. locator implementations
4. state machine
5. diagnostics helpers

`factory.py` is the explicit plugin boundary and should own:

1. named frame-locator builders
2. named protocol-geometry locator builders
3. stable construction helpers used by live and replay pipelines
4. optional registration hooks for future benchmark/debug/custom locator variants

Examples of future variants:

1. full-frame auto locator
2. ROI-constrained locator
3. protocol-aware locator helpers
4. benchmark/debug locators

### `receiver/pipeline/`

This package should contain multiple decode pipeline implementations.

Expected internal roles:

1. `interfaces.py`
2. `factory.py`
3. `live.py`
4. `replay.py`
5. future lightweight/debug/benchmark pipelines

`factory.py` should own named pipeline selection so application wiring does not import concrete live/replay constructors directly.

Important rule:

`runtime/` is not the place where pipeline variants live. `runtime/` provides infrastructure; `pipeline/` chooses how to use it.

### `receiver/reporting/`

This package should support multiple reporting backends and collector combinations.

Expected internal roles:

1. `interfaces.py`
2. `factory.py`
3. collectors
4. formatters
5. reporters / sinks

`factory.py` should be the explicit composition boundary for selecting and wiring reporter backends and collector sets.

Examples of future variants:

1. console reporter
2. JSON report sink
3. benchmark-oriented reporter
4. GUI/event-stream reporter

## 4. Required Architectural Separation

The refactor should make these boundaries explicit.

## 4.1 Information vs transport

Transport frame headers are not future semantic units.

Future OGRB work requires a separate information model:

1. `TransmissionUnit`
2. `SystematicUnit`
3. `CodedUnit`

Current frame-level header structures should remain transport-layer constructs.

## 4.2 Scheduling vs transport

Current sender scheduling is entangled with transport construction inside [controller.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/sender/application/controller.py).

That must be separated so that:

1. the scheduler chooses semantic units
2. the transport encoder renders them

This is mandatory for OGRB.

## 4.3 Runtime vs protocol details

Current runtime code already moved in the right direction, but more cleanup is required.

Runtime should not need to understand:

1. layered bootstrap internals
2. layered body profile semantics
3. future coding-equation semantics

It should only move frames and decoded results.

## 4.4 Reporting vs worker-private metadata

Worker metadata snapshots exist for runtime transport between processes, but reporting should not depend on fragile private metadata shapes.

Instead:

1. transport decoders produce normalized success/failure metadata
2. runtime forwards it unchanged
3. reporting consumes only the normalized fields

## 5. Concrete Refactor Targets

## 5.1 Sender

### Current problem

[controller.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/sender/application/controller.py) currently mixes:

1. payload packing
2. manifest/control-plane generation
3. protocol encoder selection
4. scheduling policy
5. frame stream generation
6. sender reporting metadata
7. render-loop orchestration

This file is too central and will become a bottleneck for any future OGRB implementation.

### Target split

Recommended split:

1. `sender/application/session_builder.py`
2. `sender/application/frame_stream.py`
3. `sender/application/playback.py`
4. `sender/application/reporting.py`
5. `sender/scheduling/control_payloads.py`
6. `sender/transport/factory.py`

Current status:

1. `session_builder.py` has absorbed payload/manifest/chunk construction.
2. `frame_stream.py` has absorbed encoded frame-stream generation.
3. `playback.py` has absorbed dump-only and interactive render-loop helpers.
4. `reporting.py` has absorbed sender report construction and JSON writing.
5. `runtime_state.py` has absorbed sender runtime counters and progress reporting state.
6. `presentation.py` has absorbed sender frame labels, overlay text, and window-title helpers.
7. `control_payloads.py` has absorbed control-plane payload builders.

`controller.py` should continue to shrink into a thin orchestrator over these modules and should not regain protocol-building or playback/reporting detail.

## 5.2 Receiver ROI

### Current problem

ROI-related logic exists both inside [receiver/roi/](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/roi/) and as top-level files:

1. [roi_policy.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/roi/policy.py)
2. [roi_setup.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/roi/setup.py)
3. [roi_selector.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/roi/selector.py)
4. [roi_profile.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/roi/profile.py)

### Target

All ROI logic should live under:

```text
receiver/roi/
  policy.py
  setup.py
  selector.py
  profile.py
  manager.py
  transforms.py
```

Top-level ROI files should disappear.

## 5.3 Receiver transport

### Current problem

Transport-specific decoders and adapters are still top-level:

1. [decoder_basic.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/transport/basic/decoder.py)
2. [decoder_compact.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/transport/compact/decoder.py)
3. [decoder_gray4.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/transport/gray4/decoder.py)
4. [decoder_layered.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/transport/layered/decoder.py)
5. [protocol_adapter_basic.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/transport/basic/adapter.py)
6. [protocol_adapter_compact.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/transport/compact/adapter.py)
7. [protocol_adapter_gray4.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/transport/gray4/adapter.py)
8. [protocol_adapter_layered.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/transport/layered/adapter.py)

### Target

These should move under protocol-specific transport subpackages:

```text
receiver/transport/basic/
  adapter.py
  decoder.py

receiver/transport/compact/
  adapter.py
  decoder.py

receiver/transport/gray4/
  adapter.py
  decoder.py

receiver/transport/layered/
  adapter.py
  decoder.py
  observability.py
```

This creates one high-cohesion protocol package per transport.

Current status:

1. Real decoder and adapter implementations already live under `receiver/transport/<protocol>/`.
2. Shared binary control/header decode logic has been moved under `receiver/transport/control_decode.py`.
3. Source-path imports now target these transport packages directly.
4. Protocol subpackages expose lazy public entry points via their `__init__.py` files, so package boundaries are explicit without forcing eager imports or circular dependencies.

## 5.4 Receiver reporting

### Current problem

Reporting is partially modularized, but still split across:

1. [protocol_observability.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/transport/layered/observability.py)
2. [reporter_factory.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/reporting/factory.py)
3. [stats.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/reporting/transfer_stats.py)
4. runtime-side reporting helpers in [runtime/](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/runtime/)

### Target

Reporting should be clearly divided into:

```text
receiver/reporting/
  collector.py
  report_collector.py
  stats_collector.py
  protocol_collector.py
  assembler_collector.py
  formatter.py
  reporter.py
  factory.py
```

Transport-specific observability helpers should live in the relevant transport package and export normalized data into reporting.

## 6. Recommended Dependency Direction

The refactor should enforce a one-way dependency flow.

### 6.1 Sender

```text
cli/application
  -> scheduling
  -> information
  -> transport
  -> render
  -> common
```

### 6.2 Receiver

```text
cli/application
  -> pipeline
  -> locator
  -> reporting
  -> runtime
  -> transport
  -> information
  -> common
```

### 6.3 Disallowed dependencies

Examples of dependencies that should be avoided:

1. runtime importing protocol-private decoder helpers
2. runtime deciding which pipeline variant to use internally
3. reporting importing worker-private metadata helpers
4. ROI importing runtime internals
5. transport mutating assembler state directly
6. scheduler depending on visual frame layout
7. concrete locator implementations being hard-coded into unrelated application modules

## 7. OGRB Compatibility Requirements

This refactor must leave the codebase ready for future OGRB work.

That requires:

1. a future information-layer model separate from visual frame headers
2. a scheduling layer that operates on semantic units, not transport frames
3. transport implementations that carry semantic units without redefining them

The immediate structural preparation is:

1. introduce `common/information/` as a real package
2. reserve `sender/information/` and `receiver/information/`
3. move existing transport-specific code into transport packages
4. move current sender schedule logic into `sender/scheduling/`
5. keep locator/pipeline/reporting as pluggable module families rather than singleton modules

## 8. Migration Plan

The refactor should be staged.

## Phase 1: Clean top-level package boundaries

1. move all ROI files into `receiver/roi/`
2. move receiver protocol adapters/decoders into `receiver/transport/`
3. move sender protocol adapters/encoders into `sender/transport/`
4. move report factory/formatter glue into `receiver/reporting/`
5. move pipeline implementations out of `receiver/runtime/` into `receiver/pipeline/`

This phase is mostly packaging and import cleanup.

## Phase 2: Split sender orchestration

1. reduce [controller.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/sender/application/controller.py)
2. isolate session/manifest preparation
3. isolate frame-stream assembly
4. isolate scheduling policy

This phase reduces the sender bottleneck before OGRB work begins.

## Phase 3: Introduce information-layer packages

1. add `TransmissionUnit`-oriented models
2. wrap current chunk/frame semantics in those models
3. keep implementations systematic-only at first

Current status:

1. `common/information/units.py` and `common/information/identities.py` now define the systematic-only `TransmissionUnit` model.
2. `sender/information/unit_builder.py` builds `SystematicUnit` streams from current payload chunks.
3. `sender/information/generation_builder.py` partitions payload chunks into real non-overlapping generations.
4. `receiver/information/generation_store.py` and `receiver/information/unit_acceptor.py` now host generation-aware ingest keyed by `(generation_id, source_index)`.
5. `receiver/information/assembler.py` preserves the old outward behavior while preferring information-layer ingest for data frames.

This phase did not change visual transport behavior or wire format, but it did retire the single-generation bridge assumption in favor of a real systematic generation model.

## Phase 4: Prepare scheduling abstraction

1. define scheduler interface
2. move current epoch/bootstrap/data scheduling under that interface
3. make transport encoder consume scheduled units rather than direct frame generation logic

Current status:

1. `common/scheduling/interfaces.py` now defines `ScheduledUnit`, `TransmissionSchedule`, and `UnitScheduler`.
2. `sender/scheduling/unit_schedule.py` provides a systematic-only `BroadcastUnitScheduler`.
3. `sender/application/frame_stream.py` now routes payload frames through `GenerationPlan -> SystematicUnit -> ScheduledUnit -> transport frame`.

This creates the insertion point for OGRB without changing current broadcast semantics.

Boundary-tightening exit criteria:

1. package `__init__` files expose only stable facades, not convenience dumps of implementation details
2. `application` layers depend on factories and protocols rather than concrete transport/reporting classes
3. `pipeline` code no longer imports package-root facades when a narrower submodule dependency exists
4. `debug` and `config` remain auxiliary domains and do not become default wiring surfaces

Current status:

1. the boundary-tightening criteria above are now satisfied in the current tree
2. package entrypoints have been reduced to stable facades with narrower public surfaces
3. application-layer wiring now prefers named factories and protocol interfaces over direct dependence on concrete transport/reporting implementations
4. duplicate implementation-selection edges have been removed where they overlapped, so factory selection now has a single intended path at high-level boundaries
5. this completed a structural cleanup pass and did not introduce `CodedUnit`, solver logic, or scheduler-policy behavior

Boundary maintenance rules:

1. package `__init__.py` files should remain narrow facades and must not become convenience dumps for internal helpers or concrete implementation classes
2. high-level implementation selection must continue to happen only through named factory modules; do not introduce parallel factory entrypoints
3. `sender/application/controller.py` should remain a thin orchestrator and must not absorb transport, scheduling, reporting, or rendering detail
4. `receiver/application/pipeline_factory.py` may translate app-facing parameters, but it should not grow protocol-specific or runtime-internal wiring policy
5. `receiver/reporting/`, `receiver/locator/`, and `receiver/runtime/` facades should only expose stable cross-module entrypoints; implementation details belong in submodules
6. `receiver/debug/` remains optional support code and must not become a default dependency surface for runtime, transport, or pipeline behavior
7. `receiver/config` remains a configuration domain and must not become a factory or orchestration layer
8. future structural cleanup should be incremental and local; do not start another broad package migration unless the architecture document is explicitly revised first
9. compatibility-oriented wrapper modules should not be reintroduced once the owning domain has a clear primary implementation path

## Phase 5: OGRB and erasure coding

1. implement coded information units
2. add generation state and equation handling
3. plug OGRB into scheduling

At this point the structure should already support the feature work.

Current status:

1. not started
2. `CodedUnit`, equation identity, solver/rank tracking, and OGRB scheduler policy remain future work
3. the current repository state should be treated as pre-OGRB structural groundwork

## 9. File Migration Map

This section lists the most important concrete moves.

### 9.1 Sender

- [controller.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/sender/application/controller.py)
  - split across `application/` and `scheduling/`
- [renderer_cv2.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/sender/render/renderer_cv2.py)
  - move to `render/renderer_cv2.py`
- [schedule_policy.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/sender/scheduling/broadcast_schedule.py)
  - move to `scheduling/broadcast_schedule.py`
- protocol-specific encoder/adapter files
  - move to `sender/transport/<protocol>/`

### 9.2 Receiver

- ROI files at receiver top-level
  - move into `receiver/roi/`
- decoder/protocol-adapter files at receiver top-level
  - move into `receiver/transport/<protocol>/`
- [protocol_observability.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/transport/layered/observability.py)
  - split between `receiver/reporting/` and `receiver/transport/layered/`
- [assembler.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/information/assembler.py)
  - real implementation now lives in `receiver/information/assembler.py`
- [restore.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/application/restore.py)
  - move into `receiver/application/restore.py`

Current status:

1. Top-level compatibility modules have been retired.
2. Source-path imports now target real implementation packages only.
3. `common/transport/*`, `sender/*`, and `receiver/*` subdomain packages now form the supported internal API surface.

Phase 1 done criteria:

1. Top-level modules no longer host real implementation logic.
2. Main source-path imports no longer depend on top-level transport, ROI, decoder, or sender shim modules.
3. Compatibility-layer files have been removed from the repository.
4. New subdomain paths are the only supported internal implementation paths.

Real systematic-generation phase criteria:

1. Sender payload chunks are partitioned into real non-overlapping generations before transport encoding.
2. `SystematicUnit.generation_id` and `source_index` are generation-scoped, not bridge-phase placeholders.
3. Receiver systematic ingest deduplicates by `(generation_id, source_index)`.
4. Current transport headers remain transport-only and are not extended with future OGRB semantics.

## 10. Recommended First Implementation Batch

The first practical refactor batch should be intentionally narrow.

Recommended first batch:

1. finish ROI consolidation into `receiver/roi/`
2. move receiver transport files into `receiver/transport/`
3. move sender transport files into `sender/transport/`
4. move sender renderer into `sender/render/`
5. keep behavior unchanged

Why this batch first:

1. high architectural value
2. relatively low semantic risk
3. reduces top-level clutter immediately
4. creates the right structural base for later information/scheduling work

## 11. Final Recommendation

The refactor should not start with OGRB-specific code. It should start by fixing package boundaries so the codebase has stable places for:

1. information semantics
2. scheduling policy
3. visual transport
4. pipeline implementations
5. runtime infrastructure
6. reporting
7. ROI
8. locator

The highest-value structural rule is:

**Top-level packages should contain subdomains, and swappable implementations should live behind those subdomains rather than at sender/receiver top level.**

This keeps the codebase modular now and prevents the future OGRB implementation from becoming another layer of cross-cutting complexity.
