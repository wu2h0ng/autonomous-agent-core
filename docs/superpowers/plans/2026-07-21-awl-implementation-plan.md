# AWL Architecture Recast: Implementation Plan

> Status: `DESIGN_ONLY / PLANNING / NO_RUNTIME_AUTHORIZATION`
> Date: 2026-07-21
> Source: `docs/superpowers/specs/2026-07-15-adaptive-work-loop-architecture-recast-design.md`
> Primary labels: `A/E` (architecture seam evolution, engineering acceptance)
> Route C triage status: AWL-ARCHITECTURE-RECAST is PARK per Route C triage. Founder authorized this implementation plan despite the PARK status on 2026-07-21.

## 0. Pre-Implementation Warning

Per Route C triage and the 2026-07-16 attack review: "interface infrastructure precedes mechanism evidence." AWL-1 through AWL-6 are architecture seams, not mechanism evidence. They do not advance M1/M2/M3 directly. They supply the infrastructure within which M1/M2/M3 mechanism work executes.

The stop condition is explicit: if any AWL seam implementation reaches the point where a failing test cannot be written because the consumer (SRL Runtime, W1 adaptation, Developer slice) is not yet active, implement that seam as inert infrastructure and stop. Do not invent synthetic tests to justify further seam expansion.

## 1. Current State Summary

| Asset | Location | Status |
|---|---|---|
| RunCoordinator + WorkspaceSandbox | main checkout | Working (SPINE-0 Developer golden path) |
| SRL Runtime (M0) | canonical-convergence worktree | PROPOSAL_ONLY, partial |
| TaskConfigurationSnapshot | canonical-convergence | Implemented, sealed snapshot |
| Mandate/SRL contracts | canonical-convergence | DESIGN_ONLY, typed contracts exist |
| Candidate lifecycle (ADM-P2/3/4) | separate branches | Implemented local, all-DEFER |
| AWL-0/2/5 design docs | adaptive-work-loop worktree | DOCS_ONLY, Kimi APPROVED |
| AWL-1/3/4/6 | Not designed | Requires design before implementation |

**Key gap:** The canonical-convergence SRL contracts are on a separate branch. AWL seams must be implemented on main (or a new feature branch from main) and cannot depend on unmerged canonical-convergence code.

## 2. Implementation Order and Dependencies

```
Phase 1 (independent, on main checkout):
├── AWL-1: C7 read/admin port split
├── AWL-2: Capability adapter boundary
└── AWL-4: Minimal adaptive-loop contracts (Pydantic only)

Phase 2 (requires Phase 1):
├── AWL-3: RunCoordinator strangler decomposition
└── AWL-5: Research route capsules (directory structure + import guard)

Phase 3 (requires Phase 2):
└── AWL-6: Developer adaptive vertical slice
```

Phase 1 items are logically independent and can be implemented on separate feature branches. Integration is serial by exact reviewed commits.

## 3. AWL-1: C7 Read/Admin Port Split

### Scope
Split the Runtime-facing `CorrectionSnapshotPort` from the operator-facing `CorrectionAdminPort`.

### Current code
`packages/os_core/src/agent_os_core/governance.py::CorrectionAuthority` is a single class with both read (`snapshot()`, `halted()`) and write (`correct()`, `resume()`) methods. The `RunCoordinator` receives the full `CorrectionAuthority` instance.

### What changes

**New contract:** `CorrectionReadPort` (Protocol or abstract class)
```python
class CorrectionReadPort(Protocol):
    def snapshot(self, task_id, run_id, capability_id) -> CorrectionEpochVector: ...
    def halted(self, task_id, run_id, capability_id) -> bool: ...
```

**Existing class renamed:** `CorrectionAuthority` keeps `correct()` and `resume()`, implements `CorrectionReadPort`.

**Consumers changed:**
- `RunCoordinator.__init__` accepts `CorrectionReadPort` instead of `CorrectionAuthority`
- `PolicyKernel.decide()` accepts `CorrectionReadPort`
- `CapabilityBroker.invoke()` accepts `CorrectionReadPort`
- `WorkspaceSandbox.invoke()` accepts `CorrectionReadPort`

**Files to modify:**
| File | Change |
|---|---|
| `contracts/authority.py` | Add `CorrectionReadPort` typed contract |
| `os_core/governance.py` | `CorrectionAuthority` implements `CorrectionReadPort`. Admin-only methods (`correct`, `resume`) remain only on `CorrectionAuthority`. |
| `os_core/execution.py` | `RunCoordinator` constructor takes `CorrectionReadPort` |
| `os_core/capability.py` | `CapabilityBroker`, `WorkspaceSandbox` take `CorrectionReadPort` |
| `tests/product/test_authority_contracts.py` | Add test: `CorrectionReadPort` instance has no `correct` or `resume` method accessible at type-check level |

### Entry point
`CorrectionReadPort` Pydantic Protocol in `contracts/authority.py`.

### Contract
`CorrectionReadPort` exposes `snapshot()` and `halted()` only. `CorrectionAuthority` implements both the read port and the admin write methods.

### Failure path
- If a consumer (RunCoordinator, CapabilityBroker) attempts to call `correct()` or `resume()` on a `CorrectionReadPort`, pyright must flag this as a type error.
- Runtime behavior (snapshot epochs, halt checks, linearization) remains identical.

### Test strategy
1. `test_c7_read_port_no_write_methods`: pyright type-check that `CorrectionReadPort` has no `correct`/`resume`
2. `test_c7_auth_equivalence`: existing snapshot/halted behavior unchanged
3. `test_c7_admin_still_writable`: `CorrectionAuthority` still supports `correct()`/`resume()`
4. Existing SPINE-0 golden path tests must pass without modification

### Risk assessment
- **Low risk to authority spine**: The split is syntactic (type-level), not behavioral. No C7 semantics change.
- **Low risk to existing tests**: Only constructor signatures change, behavior preserved.
- **Known limitation**: Physical process/DB-role/key isolation is deferred to post-production gate (per design doc).

### Stop condition
- Pyright verifies `CorrectionReadPort` has no write methods
- All 16 existing product tests pass
- No new behavior, only port-level read/write separation

### Estimated effort
~1 session (type-level refactor, no behavioral change)

---

## 4. AWL-2: Capability Adapter Boundary

### Scope
Core retains `CapabilityPort`, `CapabilityBroker`, `ActionPermit`, `CapabilityReceipt`. Repository workspace behavior moves behind a `DeveloperAdapter`. Core constructors no longer depend on `WorkspaceSandbox`.

### Current code
`RunCoordinator.__init__` takes a `WorkspaceSandbox` instance. `WorkspaceSandbox` contains developer-specific behavior (workspace.read, workspace.apply_patch, workspace.run_tests). The Core mixes generic capability dispatch with developer-specific workspace semantics.

### What changes

**New interfaces:**
- `CapabilityPort` (Protocol): the generic capability dispatch interface that Core depends on
- `DeveloperAdapter`: implements `CapabilityPort` with workspace sandbox behavior
- `WorkspaceSandbox` becomes an internal implementation detail of `DeveloperAdapter`

**Files to create/modify:**
| File | Change |
|---|---|
| `contracts/capability.py` | Add `CapabilityPort` Protocol |
| `os_core/capability.py` | `CapabilityBroker` calls `CapabilityPort.invoke()`. `WorkspaceSandbox` stays but is no longer referenced by Core constructors. |
| `os_core/execution.py` | `RunCoordinator` takes `CapabilityPort` instead of `WorkspaceSandbox` |
| `apps/developer_adapter.py` | NEW: `DeveloperAdapter implements CapabilityPort`, wraps `WorkspaceSandbox` |
| `tests/product/test_spine0_golden_path.py` | Use `DeveloperAdapter` instead of `WorkspaceSandbox` in test fixtures |
| `tests/product/test_capability_adapter.py` | NEW: `DeveloperAdapter` behavior equivalent to `WorkspaceSandbox` |

### Entry point
`CapabilityPort` Protocol in `contracts/capability.py`.

### Contract
```python
class CapabilityPort(Protocol):
    def invoke(self, action, permit, correction_read, attempt) -> CapabilityResult: ...
    def compensate(self, action, permit, correction_read) -> CompensationReceipt: ...
```

### Failure path
- `CapabilityBroker` validates `permit.matches(action)` before delegating to `CapabilityPort`
- `DeveloperAdapter` preserves all workspace safety (path sandbox, no symlinks, allowlisted commands, idempotency)
- If `DeveloperAdapter` fails to produce equivalent behavior, the equivalence test suite catches it

### Test strategy
1. `test_developer_adapter_equivalence`: DeveloperAdapter produces identical CapabilityResult to WorkspaceSandbox for all three specs (read/apply_patch/run_tests)
2. `test_capability_port_no_developer_semantics`: Core constructors (RunCoordinator, CapabilityBroker) reference only CapabilityPort, no WorkspaceSandbox type
3. `test_capability_port_arbitrary_adapter`: A trivial mock CapabilityPort implementation works with RunCoordinator
4. All existing SPINE-0 golden path tests pass with DeveloperAdapter

### Risk assessment
- **Medium risk**: Adapter indirection adds a layer. Equivalence must be proven.
- **No authority change**: WorkspaceSandbox safety invariants preserved.
- **Opens door for non-workspace adapters** (SQL, browser, Data Agent) but no new adapters in this scope.

### Stop condition
- Core constructors reference only `CapabilityPort`, not `WorkspaceSandbox`
- `DeveloperAdapter` equivalence tests pass
- All existing product tests pass
- No SQL/browser/Data Agent adapters created

### Estimated effort
~1-2 sessions (extract interface + wrap existing code + equivalence tests)

---

## 5. AWL-4: Minimal Adaptive-Loop Contracts

### Scope
Add the 10 contracts from design §5 as Pydantic models in `packages/contracts/` without Runtime integration, generation, or activation. These are typed schema contracts only.

### Specific contracts to add

| Contract | File |
|---|---|
| `EnvironmentModelSnapshot` | `contracts/environment.py` |
| `BeliefRecord` | `contracts/belief.py` |
| `BeliefPatch` | `contracts/belief.py` |
| `EvaluationContract` | `contracts/evaluation.py` (extend existing) |
| `EvaluationReceipt` | `contracts/evaluation.py` |
| `OutcomeAttributionCandidate` | `contracts/outcome.py` (extend existing) |
| `ProcedureCandidate` | `contracts/candidate.py` |
| `PromotionDecision` | `contracts/candidate.py` |
| `RollbackReceipt` | `contracts/candidate.py` |
| `TaskConfigurationSnapshot` | Already exists in canonical-convergence; merge contract to main |

### What NOT to implement
- No Runtime consumption of these contracts
- No state updater, belief assembler, or evaluation runner
- No automatic generation or activation
- No persistence seams

### Entry point
Each contract is a standalone Pydantic `ContractModel` in its respective file.

### Test strategy
1. Round-trip serialization for each contract
2. Canonical digest determinism
3. Version drift detection (incompatible schema versions rejected)
4. Required field validation
5. No Runtime import of these contracts in os_core (they are contracts, not implementations)

### Risk assessment
- **Low risk**: Pydantic contracts only, no behavioral change.
- **Risk of premature expansion**: The design warns "freeze interface breadth." Implement contracts with their named consumer and stop. Do not add fields "just in case."

### Stop condition
- All 10 contracts have round-trip, digest, validation tests
- Pyright/Ruff clean
- No Runtime code references these contracts (pure contracts package)

### Estimated effort
~1 session (10 typed contracts + tests)

---

## 6. AWL-3: RunCoordinator Strangler Decomposition

### Scope
Extract behavior-preserving components from `RunCoordinator` one at a time, behind the existing public facade:

1. `GraphScheduler` (topological sort + next-node selection)
2. `NodeHandlerRegistry` (dispatch node type → execute method)
3. `ActionPipeline` (build contract → policy → permit → broker → receipt)
4. `RunStateMachine` (event transitions)
5. `ProposalEngine` (provider call → proposal parse → validation)
6. `OutcomePipeline` (evaluate + record)

### Contract
Each extracted component has a Protocol interface and a single implementation. The `RunCoordinator` facade remains the public API. New adaptive behavior cannot be added to old `if/elif NodeKind` dispatcher during decomposition.

### Files to create/modify

| File | Change |
|---|---|
| `os_core/execution.py` | `RunCoordinator` facade delegates to components |
| `os_core/graph_scheduler.py` | NEW: `GraphScheduler` extracted |
| `os_core/node_handlers.py` | NEW: `NodeHandlerRegistry` extracted |
| `os_core/action_pipeline.py` | NEW: `ActionPipeline` extracted |
| `os_core/proposal_engine.py` | NEW: `ProposalEngine` extracted |
| `os_core/run_state.py` | NEW: `RunStateMachine` extracted |
| `os_core/outcome_pipeline.py` | NEW: `OutcomePipeline` extracted |

### Entry point
`RunCoordinator.run()` remains the single public entry, delegating internally.

### Test strategy
1. For each extraction: existing SPINE-0 tests must pass with zero changes
2. Component unit tests: each component tested in isolation with mocked dependencies
3. Event order and digest equivalence tests: behavior-preservation proof
4. No test regression in full product suite

### Risk assessment
- **Medium risk**: The RunCoordinator is ~500 lines of procedural code. Extracting components without changing behavior requires discipline.
- **Anti-pattern to avoid**: fixing bugs during extraction. Extract first, fix separately.
- **No new behavior**: decomposition only. LOOP/PARALLEL_MAP/SUBWORKFLOW remain UnsupportedNodeError.

### Stop condition
- Each component has unit tests
- Full SPINE-0 golden path unchanged
- Full product suite passes
- RunCoordinator.run() no longer contains a procedural if/elif/else chain over NodeKind

### Estimated effort
~2-3 sessions (6 component extractions + equivalence verification)

---

## 7. AWL-5: Research Route Capsules

### Scope
Create directory structure and import guard. No history move, no code import, no route activation.

### Directory structure
```
research/routes/
  <route_id>/
    mechanism/
    environment/
    evaluator/
    prereg/
    result/
research/common/
promotion_candidates/
```

### Import guard
Product code cannot import from `research/routes/` or `research/`. A mechanical lint rule (Ruff check) enforces this.

### Files to create
| File | Change |
|---|---|
| `research/routes/__init__.py` | NEW: empty |
| `research/routes/README.md` | NEW: route capsule spec, admission rules |
| `ruff.toml` (existing) | Add rule: `"research.routes"` imports banned in `packages/` and `apps/` |

### What NOT to do
- Do not move any existing research files
- Do not activate any route
- Do not implement route-to-product adapters

### Stop condition
- Directory structure exists
- Ruff enforcement passes: product code importing from research/routes fails lint

### Estimated effort
~0.5 sessions (directory creation + lint rule)

---

## 8. AWL-6: Developer Adaptive Vertical Slice

### Scope
One black-box software environment with executable truth, reversible probes, hidden tests, and version drift. Demonstrates the full AWL cycle:

```
observe → state/belief update → probe or abstain
→ compile immutable configuration → governed execution
→ verified outcome → attribution candidate
→ external evaluation → later-run promotion/canary/rollback
```

### Prerequisites
- AWL-1 (C7 ports), AWL-2 (capability adapter), AWL-3 (coordinator decomposition), AWL-4 (loop contracts), AWL-5 (route capsules) all completed
- TaskConfigurationSnapshot merged to main
- ADM-P2/3/4 candidate lifecycle infrastructure available

### What it tests
Compares Agent OS adaptive path against:
1. Direct model-plus-tools (single LLM call with workspace access)
2. Static workflow (fixed DAG, no adaptation)
3. Retrieval/summary baseline
4. Simple systematic probing

### Stop condition
- One end-to-end path complete
- Comparison against named baselines
- Null/negative result acceptable: does not prove autonomy or generality

### Estimated effort
~4-5 sessions (full vertical slice integration)

---

## 9. Feature Branch Strategy

| Subproject | Branch name | Base |
|---|---|---|
| AWL-1 | `feature/awl-1-c7-port-split` | `main` |
| AWL-2 | `feature/awl-2-capability-adapter` | `main` |
| AWL-4 | `feature/awl-4-loop-contracts` | `main` |
| AWL-3 | `feature/awl-3-coordinator-decomposition` | After AWL-1 + AWL-2 |
| AWL-5 | `feature/awl-5-route-capsules` | `main` |
| AWL-6 | `feature/awl-6-developer-slice` | After AWL-3 + AWL-4 + AWL-5 |

Phase 1 branches (AWL-1, AWL-2, AWL-4, AWL-5) can be created in parallel. Phase 2/3 branches are sequential.

Each branch:
- One writer
- Bypass-detecting tests before implementation
- Independent exact-head review
- Clean Ruff/Pyright/Pyright/diff
- No main push/merge without founder authorization

---

## 10. What Is NOT Authorized

- Microservices, distributed transactions, or service mesh
- Rust rewrite
- Generic Data Fabric
- New fixed vertical Domain Packs
- Data Agent subtree migration or runtime cross-import
- L4 active-runtime self-modification
- L5 safety-root mutation
- Provider-specific product identity
- Model training before stable held-out ceiling
- Large long-horizon experiments unrelated to this slice
- Result, Product Alpha, production, superiority, generality, autonomy, or AGI claims

---

## 11. Total Estimated Effort

| Phase | Subprojects | Sessions |
|---|---|---|
| Phase 1 | AWL-1 + AWL-2 + AWL-4 + AWL-5 | 4-5 |
| Phase 2 | AWL-3 | 2-3 |
| Phase 3 | AWL-6 | 4-5 |
| **Total** | | **10-13 sessions** |

This assumes dedicated implementation sessions with clean reviews. Does not include review turnaround time, merge conflicts, or scope creep.
