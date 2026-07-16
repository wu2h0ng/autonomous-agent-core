# P-SRL-RUNTIME-1: Situated Responsibility Loop Runtime — Design Candidate

> Date: 2026-07-16
> Status: `DESIGN_CANDIDATE / NO_IMPLEMENTATION / NO_RUNTIME_AUTHORIZATION`
> Track: `P/A/E` — product capability, architecture invariant, engineering acceptance
> Scope: minimal SRL Runtime vertical above the existing Task/Run/Action spine
> Depends on: `docs/research/situated-responsibility-loop-architecture-2026-07-16.md`, `docs/research/situated-operational-model-architecture-2026-07-16.md`, `docs/architecture/A-SRL-1-threat-model-and-authority-invariants.md`
> Primary labels: `P` implements named `U`; `A` protects permanent boundaries; `E` verifies invariants.

## 1. Decision

Implement a minimal, fail-closed SRL Runtime that consumes the ratified `Mandate`, `StandingMission`, `EnvironmentBinding`, `SrlEnvironmentEvent`, `SrlRelevanceAssessment` and `SrlHelpRequest` contracts and produces bounded, authority-audited work on the existing Task/Run/Action spine. The Runtime does not introduce a new general-autonomy claim; it is a governed bridge from continuous situated responsibility to bounded task execution.

The design keeps the existing Task/Run/Action spine unchanged as the execution organ and adds only the SRL-specific orchestration layer required by A-SRL-1 invariants I-4, I-8 and I-11 through I-25.

## 2. User outcome (`U`)

A principal can ratify a continuing `Mandate`, authorize one or more `EnvironmentBinding`s, and have the system:

1. receive immutable, deduplicated environment events;
2. assess event relevance under a ratified policy and produce a typed, replayable `SrlRelevanceAssessment`;
3. form a bounded `ProposedGoal` when the assessment disposition permits;
4. activate a Task only after an explicit authority record and Mandate-envelope checks;
5. emit structured `SrlHelpRequest`s when information, authority or safety is missing;
6. enforce wake/query/help budgets and fail closed when they are exceeded;
7. accept outcome updates only from the trusted `DeterministicOutcomeEvaluator` registry.

The operator's hidden cognitive work — state maintenance, change detection, relevance judgment, next-step generation — is reduced only to the extent that the above steps happen correctly inside the envelope and produce auditable evidence.

## 3. Product capability (`P`)

### 3.1 Public entry points

| Entry point | File | Responsibility |
|---|---|---|
| `SrlRuntime.evaluate_event` | `packages/os_core/src/agent_os_core/srl_runtime.py` | Accept an `SrlEnvironmentEvent` and return a bounded `SrlEvaluationResult` (IGNORE, OBSERVE, INVESTIGATE, PROPOSED_GOAL, HELP, BUDGET_HALT). No side effects beyond durable logging. |
| `SrlRuntime.propose_goal` | `packages/os_core/src/agent_os_core/srl_runtime.py` | Turn an INVESTIGATE/CREATE_TASK assessment into a `ProposedGoal` with digest-bound authority references. Proposal only. |
| `SrlRuntime.activate_goal` | `packages/os_core/src/agent_os_core/srl_runtime.py` | Promote a `ProposedGoal` to a Task via the existing `TaskService` after Mandate-envelope, C7 and capability checks. |
| `SrlRuntime.emit_help_request` | `packages/os_core/src/agent_os_core/srl_runtime.py` | Create an `SrlHelpRequest`, charge the help budget ledger, and suspend non-continuable work. |
| `SrlRuntime.resolve_help_request` | `packages/os_core/src/agent_os_core/srl_runtime.py` | Accept a typed `SrlHelpResponse` (`OperatorDecision`/`CapabilityGrant`) and resume or redirect affected work. |
| `SrlRuntime.accept_outcome` | `packages/os_core/src/agent_os_core/srl_runtime.py` | Update mission/portfolio state only when a trusted evaluator `ObservedOutcome` is provided. |

### 3.2 Runtime internal ports

```text
SrlRuntime
├── EventLedgerPort         (immutable, deduplicated event log)
├── MandateRegistryPort     (ratified Mandate + StandingMission versions)
├── AssessorPort            (policy-bound relevance assessment; proposal only)
├── GoalFormationPort       (ProposedGoal from assessment + mission)
├── BudgetEnforcementPort   (wake/query/help budgets)
├── HelpDispatchPort        (SrlHelpRequest lifecycle)
├── TaskActivationPort      (existing TaskService wrapper)
├── OutcomeAcceptorPort     (consume trusted evaluator output)
└── AuditPort               (non-erasable transition records)
```

Every port is versioned and independently attributed. No single `instance_id`/`version` may both produce evidence and emit the authority record that accepts it (I-23).

## 4. Architecture invariants (`A`)

### 4.1 Mapping to A-SRL-1 RT invariants

| Invariant | Runtime enforcement point | Failure mode |
|---|---|---|
| I-4 StandingMission parent digest matches current ratified Mandate | `MandateRegistryPort.current_ratified_mission()` rejects mismatch | Reject mission; stop work |
| I-8 Assessor version/policy digest matches ratified policy | `AssessorPort.assess()` validates `assessor_version` + `assessor_policy_digest` against registry | Reject assessment; emit HELP if repeated |
| I-11 HelpBurdenReceipt flips to EXCEEDED | `BudgetEnforcementPort.charge_help()` delegates to separate `HelpBurdenLedger` | Force `HELP_BURDEN_EXCEEDED` outcome |
| I-12 Duplicate dedupe_key rejected/idempotent | `EventLedgerPort.append()` enforces uniqueness per binding | Reject/no-op |
| I-13 Wake/query budget exhausted → fail-closed | `BudgetEnforcementPort.check_binding_budget()` before poll/subscribe | Stop binding; emit HELP/REVOCATION_REQUEST |
| I-14 No SRL organ creates ActionPermit/CapabilityGrant/ActionReceipt | `TaskActivationPort` only consumes existing authority spine | Reject |
| I-15 Outcome updates require trusted ObservedOutcome | `OutcomeAcceptorPort.accept()` checks evaluator registry signature | Reject untrusted interpretation |
| I-16 StandingMission rejected if Mandate not RATIFIED/ACTIVE or expired | `MandateRegistryPort.current_ratified_mission()` validates status and expiry | Reject |
| I-18 Read-only binding rejects write-effect proposals | `GoalFormationPort` checks binding `write_capability_id` and capability envelope | Reject |
| I-20 After help expiry only continuable work continues | `HelpDispatchPort.resolve()` suspends non-continuable work | Suspend |
| I-21 HelpBurdenReceipt computed by ledger separate from emitter | `HelpDispatchPort` emits request; `BudgetEnforcementPort` computes receipt | Reject self-computed receipt |
| I-22 W1/W2 updates cannot mutate Mandate/Envelope/Mission/grants | `Runtime` refuses any update object of those types from W1/W2 channel | Reject |
| I-23 No single instance both proposes and accepts | Authority records carry producer `instance_id`; acceptance records carry distinct `instance_id` | Reject |
| I-25 Cross-restart replay idempotent | `EventLedgerPort` persistent dedupe + `SrlEvaluationResult` idempotency key | No-op |

### 4.2 Authority separation

- **C7 remains external.** The Runtime calls a `C7CheckPort` before any activation; no SRL organ can disable or override it.
- **Permission ceiling.** The Runtime may narrow the Mandate envelope internally but never widen it.
- **Non-erasable audit.** Every `event → assessment → proposed goal → task activation → outcome → W1/W2 update` transition is recorded with digests, timestamps and authority references.

## 5. Engineering acceptance (`E`)

### 5.1 Test classes required before implementation admission

1. **Contract-level RED tests** already exist for V0/V1 invariants I-1, I-2, I-3, I-5, I-6, I-7, I-9, I-10, I-17, I-19, I-24.
2. **Adapter-level RED tests** (`tests/product/test_srl_runtime_invariants.py`) construct events/assessments and attempt to drive the Task spine directly; verify rejection for I-4, I-8, I-12, I-14, I-16, I-18, I-20, I-22, I-23.
3. **Budget exhaustion tests** for I-11, I-13, I-21.
4. **Replay/deduplication tests** for I-12, I-25.
5. **Authority separation tests** for I-23.
6. **Outcome-truth coupling tests** for I-15.
7. **C7 bypass tests** attempt to disable C7 from within an SRL organ.

### 5.2 Implementation sequence

1. **M0 — ports and in-memory stubs** (no persistence, no provider calls)
   - `SrlRuntime` class with typed port protocols
   - `InMemoryEventLedger`, `InMemoryMandateRegistry`, `InMemoryBudgetLedger`
   - `AssessorPort` returns deterministic fixture assessments for tests
   - RED tests for all RT invariants
2. **M1 — policy-bound assessor integration**
   - Connect `AssessorPort` to existing provider/relevance pipeline using `SrlRelevanceAssessment` contracts
   - Add provider invocation receipt validation
3. **M2 — Task activation integration**
   - Connect `TaskActivationPort` to `TaskService`
   - C7 and capability envelope checks
4. **M3 — persistence and restart**
   - Postgres-backed `EventLedger`, `MandateRegistry`, `BudgetLedger`
   - Cross-restart idempotency (I-25)
5. **M4 — outcome acceptor and W1/W2**
   - Connect `OutcomeAcceptorPort` to `DeterministicOutcomeEvaluator` registry
   - Confine W1/W2 updates to in-envelope tactics

### 5.3 File plan

```text
packages/os_core/src/agent_os_core/
  srl_runtime.py          # public Runtime orchestrator
  srl_ports.py            # Protocol definitions for internal ports
  srl_event_ledger.py     # EventLedgerPort implementation
  srl_mandate_registry.py # MandateRegistryPort implementation
  srl_budget_ledger.py    # BudgetEnforcementPort implementation
  srl_help_dispatch.py    # HelpDispatchPort implementation
  srl_goal_formation.py   # GoalFormationPort implementation
  srl_outcome_acceptor.py # OutcomeAcceptorPort implementation
  srl_audit.py            # AuditPort implementation

tests/product/
  test_srl_runtime_invariants.py
  test_srl_runtime_budgets.py
  test_srl_runtime_replay.py
```

## 6. Boundaries and non-claims

- This is a **bounded local runtime slice**, not general autonomy, AGI or production release.
- No new model training, provider fine-tuning or external effect authority is introduced.
- The Runtime does not replace the existing Task/Run/Action spine; it sits above it.
- No main-branch merge, push or release without separate authorization and independent review.
- R-SRL-1 result run remains gated on independent methodology review and environment/scorer freeze.

## 7. Open questions for independent design review

1. Should `AssessorPort` be a separate OS process/container to enforce I-23 authority separation at the OS level, or is instance-id/version separation sufficient for the first slice?
2. Should the initial `ProposedGoal` carry a complete `WorkflowGraph` draft, or only a goal statement + capability requirements leaving graph compilation to AWL?
3. How does the Runtime interact with ADM-P1/P2/P3/P4 inert adaptation infrastructure without activating it?
4. Which existing persistence layer (`persistence.py`, `postgres.py`, `event_store.py`) should back `EventLedgerPort` and `AuditPort`?
5. What is the minimal Customer-0 scenario that can exercise this Runtime end-to-end without requiring a real external event source?
