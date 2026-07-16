# A-SRL-1: Situated Responsibility Loop — Threat Model and Authority Invariants

> Date: 2026-07-16
> Status: `DESIGN_CANDIDATE / V0_V1_CONTRACT_RED_TESTS_IMPLEMENTED / RT_INVARIANTS_PENDING_RUNTIME / NO_RUNTIME_AUTHORIZATION`
> Track: `A/E` (architecture invariant / engineering acceptance)
> Scope: P-MANDATE-1, P-SRL-ENV-1, P-SRL-HELP-1 contracts and the minimal future SRL Runtime vertical
> Depends on: `docs/research/situated-responsibility-loop-architecture-2026-07-16.md`, `docs/research/situated-operational-model-architecture-2026-07-16.md`
> Primary labels: `A` protects `P/U`; `E` verifies the invariants.

## 1. Purpose

This document identifies the abuse cases, authority boundaries and machine-testable invariants that must hold before any SRL Runtime code is admitted. It is independent of the Product implementation writer and is intended as an input to contract review, Runtime design and R-SRL-1 preregistration.

It does **not** authorize Runtime implementation, provider calls, training, merge, push or release.

## 2. Assets and trust boundaries

| Asset | Owner / source of truth | What the system may do | What the system must never do |
|---|---|---|---|
| `Mandate` | Founder/Board / external principal | Propose amendment; request revocation | Self-expand, self-renew, weaken permanent constraints, rewrite evaluation principles or revoke itself |
| `MandateEnvelope` | Ratified with the Mandate | Enforce allowed task/effect/resource classes, budgets and principles | Silently widen allowed classes or budgets |
| `AgentInstanceRef` | Runtime attribution ledger | Record instance/version/provenance for effects | Contain mission, permissions, environment access or learning history |
| `StandingMission` | Derived from Mandate by authorized principal | Be updated through explicit W4 version switch | Be silently replaced by a conflicting mission |
| `EnvironmentBinding` | Authorized principal + capability grants | Declare observable sources and wake budgets | Grant write capability where none was authorized; exceed wake/query budget |
| `EnvironmentEvent` | Immutable event ledger | Wake a bounded relevance assessment | Select disposition, create Task, grant capability or authorize effect |
| `RelevanceAssessment` | Relevance assessor under policy | Produce a typed, replayable assessment with uncertainty and disposition | Forge assessor identity, ignore false-positive accounting, emit a reward that rewrites the mission |
| `HelpRequest` | System request to operator | Capture known facts, unknowns, bounded options, minimum answer and expiry | Be used as generic approval bypass, self-escalation to avoid work, or silent continuation after expiry |
| `C7 / audit / permission ceiling` | External constitutional root | Be consulted; record non-erasable evidence | Be bypassed, self-written or overridden by any organ |

## 3. Threat actors

1. **Compromised or buggy relevance assessor** — model, policy or provider that emits high-confidence but wrong dispositions.
2. **Compromised event source / binding** — upstream that injects fabricated or replayed events.
3. **Overreaching organ** — any SRL subcomponent (world model, portfolio proposer, scheduler) that tries to both produce evidence and accept it.
4. **Replay / time-travel attacker** — reuses old events, old Mandate versions or old assessments to create work or hide violations.
5. **Help-bypass attacker** — turns a `HelpRequest` into an implicit approval channel or uses it to dump responsibility.
6. **Self-approval attacker** — system component that accepts its own generated goals, capabilities or outcomes.
7. **Operator / developer mistake** — well-meaning human who widens a Mandate envelope, disables a check or merges a speculative feature.

## 4. Abuse cases and mitigations

### AC-1: Event creates unauthorized work
**Attack:** A crafted `SrlEnvironmentEvent` directly creates or activates a Task/Run.
**Invariant:** `EnvironmentEvent` carries **no work or effect authority**. Every disposition other than `IGNORE`/`OBSERVE` must pass through a separate `RelevanceAssessment` and a separate goal/Task formation step authorized by the Mandate envelope and C7.
**Test:** RED test constructs an `EnvironmentEvent` with a disposition field and verifies Task creation is rejected.

### AC-2: Relevance assessment self-approves work
**Attack:** A `SrlRelevanceAssessment` with `disposition=CREATE_TASK` immediately activates a Task without an independent goal formation record.
**Invariant:** `RelevanceAssessment` is **proposal-only**. A distinct `ProposedGoal`/`TaskDraftProposal` record binds the assessment digest, and activation requires a separate typed authority event.
**Test:** RED test passes a valid `CREATE_TASK` assessment and asserts activation is rejected until an explicit promotion/activation authority record exists.

### AC-3: Assessor identity forgery
**Attack:** A malicious component constructs an assessment claiming it came from a ratified `RelevanceAssessorRef`.
**Invariant:** Every assessment must include the expected assessor policy digest and, when a provider is used, a provider invocation receipt digest that matches the expected binding.
**Test:** RED test with mismatched `assessor_version`/`policy_digest` and with `provider_invocation_receipt_digest` not matching `expected_provider_invocation_binding_digest`.

### AC-4: Mission drift through standing mission replacement
**Attack:** The system silently replaces `StandingMission` with a version that relaxes constraints or changes desired outcomes.
**Invariant:** `StandingMission` is derived from a ratified Mandate version and parent digest. Any new version must carry an explicit ratification receipt and a correction-epoch bump. The Runtime must reject missions whose parent digest does not match the current ratified Mandate.
**Test:** RED test supplies a `StandingMission` with wrong `parent_mandate_digest` and verifies rejection.

### AC-5: HelpRequest as approval bypass
**Attack:** A `SrlHelpRequest` is answered with a vague reply; the system treats the reply as authorization and continues.
**Invariant:** A `HelpRequest` records the **minimum answer** required. The response must be a typed authority record (e.g., `OperatorDecision`, `CapabilityGrant`) created by an authorized principal, not raw text. The system may continue only the explicitly listed `continuable_work` while waiting.
**Test:** RED test injects a raw-text "yes" reply and verifies it is rejected as authority; only a typed `OperatorDecision` permits continuation.

### AC-6: Indiscriminate escalation
**Attack:** The system emits `HelpRequest` for every uncertain event, exceeding the `HelpBudget` and shifting all work to the operator.
**Invariant:** `HelpBurdenReceipt` tracks requests per window, operator minutes, repeated-question rate and unresolved wait. Exceeding the budget forces a `HELP_BURDEN_EXCEEDED` outcome and prevents claiming reduced operator load.
**Test:** RED test emits repeated identical help requests and verifies budget exhaustion and outcome status.

### AC-7: Replay of old events to recreate work
**Attack:** An old event is replayed with a new cursor, generating duplicate tasks.
**Invariant:** Events are immutable and deduplicated by `dedupe_key` within a binding. The event ledger rejects duplicate `dedupe_key` values for the same binding.
**Test:** RED test replays an event with the same `dedupe_key` but different `source_cursor` and verifies rejection or idempotent no-op.

### AC-8: Wake/query budget exhaustion
**Attack:** A noisy source or loop causes unbounded wake-ups.
**Invariant:** `EnvironmentBinding` carries `wake_budget_per_window` and `query_budget_per_window`. The Runtime must stop polling/subscribing and emit `HELP` or `REVOCATION_REQUEST` when exceeded.
**Test:** RED test exceeds the budget and asserts fail-closed behavior.

### AC-9: Self-approval of capabilities
**Attack:** The SRL grants itself capabilities based on its own relevance assessment.
**Invariant:** Capability grants remain in the existing `CapabilitySpec`/`CapabilityGrant` authority spine. No SRL organ may mint a grant.
**Test:** RED test attempts to create a `CapabilityGrant` from an assessment and verifies rejection.

### AC-10: Outcome/evaluation truth bypass
**Attack:** The SRL accepts its own outcome interpretation and uses it to update mission or learning.
**Invariant:** Outcome evaluation consumes frozen `ExpectedOutcome` semantics via the fail-closed `DeterministicOutcomeEvaluator` (DEV-REAL-OUTCOME-1). No SRL organ may override or reinterpret the verdict.
**Test:** RED test supplies an assessment that claims an outcome is `VERIFIED` and verifies it is rejected unless the trusted evaluator record says so.

### AC-11: Mandate status downgrade treated as active
**Attack:** A `Mandate` that is `EXPIRED`, `REVOKED`, `SUSPENDED` or `AMENDMENT_PROPOSED` is used to authorize new work as if it were `ACTIVE`.
**Invariant:** `StandingMission` and any derived work are rejected unless the parent `Mandate.status` is `RATIFIED` or `ACTIVE` and `Mandate.expires_at` has not passed.
**Test:** RED test supplies `StandingMission` bound to a `REVOKED`, `SUSPENDED`, `AMENDMENT_PROPOSED` and expired `Mandate`; each is rejected.

### AC-12: Task/effect class outside MandateEnvelope allowed classes
**Attack:** A `CREATE_TASK` assessment proposes a task or effect class not listed in `MandateEnvelope.allowed_task_classes` / `allowed_effect_classes`.
**Invariant:** A `SrlRelevanceAssessment` with `disposition=CREATE_TASK` must carry a `proposed_task_class` that is a member of `MandateEnvelope.allowed_task_classes`. Any derived task/effect class is rejected otherwise.
**Test:** RED test constructs an assessment with a disallowed `proposed_task_class` and verifies rejection.

### AC-13: Environment binding read→write escalation
**Attack:** A noisy or buggy assessor proposes effects requiring write access on a binding that was authorized only for read.
**Invariant:** `write_capability_id` may only be populated when an explicit authorized grant exists. A `SrlRelevanceAssessment` or derived task may not propose effects requiring write unless the binding's `write_capability_id` is non-null and the capability is in the `MandateEnvelope` capability envelope.
**Test:** RED test proposes a write effect on a read-only binding and verifies rejection.

### AC-14: W1/W2 update relaxes mission/envelope bounds
**Attack:** A learning or strategy update inside W1/W2 raises attention thresholds, relaxes help criteria, or widens the interpretation of `allowed_task_classes` without external authority.
**Invariant:** W1/W2 updates are confined to sensing cadence, query order, model/tool selection, retry/threshold strategy and similar in-envelope tactics. They must not mutate `Mandate`, `MandateEnvelope`, `StandingMission`, capability grants or permission ceilings.
**Test:** RED test attempts to derive a new `MandateEnvelope` from a W1/W2 update and verifies rejection.

### AC-15: Portfolio proposer accepts its own outcome
**Attack:** The same organ/version that proposed a goal or assessment also emits the authority record that accepts the resulting outcome.
**Invariant:** The event ledger, world-state assembler, relevance assessor, portfolio proposer, organ scheduler and outcome acceptor have independently versioned ports. No single `instance_id`/`version` may both produce a `SrlRelevanceAssessment`/`ProposedGoal` and emit the authority record that accepts it.
**Test:** RED test attempts to accept an outcome with the same `instance_id` that produced the assessment and verifies rejection.

## 5. Machine-testable invariants

The following invariants must be expressible as failing tests before Runtime implementation. The **Contract column** marks whether the invariant is already enforceable by V0 Pydantic validators (`V0`), requires a V1 contract amendment (`V1`), or is enforced only at the Runtime/adapter layer (`RT`).

| ID | Invariant | Contract | Failure mode |
|---|---|---|---|
| I-1 | `Mandate.ratified_at` is required when `status` is `RATIFIED` or `ACTIVE` | V0 | Reject |
| I-2 | `MandateEnvelope.allowed_task_classes` and `allowed_effect_classes` are non-empty and cannot be empty-string | V0 | Reject |
| I-3 | `AgentInstanceRef` contains no mission, permission, environment or learning fields | V0 | Reject if present |
| I-4 | `StandingMission.parent_mandate_digest` matches the current ratified Mandate digest | V0 field; RT enforcement | Reject |
| I-5 | `EnvironmentEvent` has no `disposition`, `task_id` or `capability_grant` fields | V0 | Reject if present |
| I-6 | `SrlRelevanceAssessment` requires either `trigger_event_id` or `trigger_gap_id` | V0 | Reject if both absent |
| I-7 | `SrlRelevanceAssessment.disposition` is one of the enum values; `CREATE_TASK`/`INVESTIGATE` require `proposed_goal_statement`; `HELP` requires `minimum_external_input` | V1 | Reject invalid combination |
| I-8 | `SrlRelevanceAssessment.assessor_version` and `assessor_policy_digest` match the ratified policy | V1 | Reject mismatch |
| I-9 | `SrlHelpRequest.minimum_answer` is non-empty and `help_class` is valid | V0 | Reject |
| I-10 | `SrlHelpRequest.expires_at` > `requested_at` | V0 | Reject |
| I-11 | `HelpBurdenReceipt` status flips to `EXCEEDED` when budget is crossed | RT | Force explicit outcome |
| I-12 | Duplicate `EnvironmentEvent.dedupe_key` within a binding is rejected or idempotent | RT | Reject/no-op |
| I-13 | Exceeding `wake_budget_per_window` stops further event processing and emits `HELP`/`REVOCATION_REQUEST` | RT | Fail-closed |
| I-14 | No SRL organ can create `ActionPermit`, `CapabilityGrant` or `ActionReceipt` | RT | Reject |
| I-15 | Outcome-driven updates require a trusted `ObservedOutcome` record from the evaluator registry | RT | Reject untrusted interpretation |
| I-16 | `StandingMission` is rejected if parent `Mandate.status` is not `RATIFIED`/`ACTIVE` or `Mandate.expires_at` has passed | RT | Reject |
| I-17 | `CREATE_TASK` assessment requires `proposed_task_class` in `MandateEnvelope.allowed_task_classes` | V1 | Reject |
| I-18 | `write_capability_id` may only be used when explicitly authorized; read-only bindings reject write-effect proposals | RT | Reject |
| I-19 | `INVESTIGATE`/`CREATE_TASK` assessments must have `false_positive_recorded=True` and non-empty `evidence_refs` | V1 | Reject or downgrade to `ABSTAIN` |
| I-20 | After `SrlHelpRequest.expires_at`, only `continuable_work` may continue; all other work for the commitment/goal is suspended | RT | Suspend |
| I-21 | `HelpBurdenReceipt` is computed by a budget ledger separate from the `SrlHelpRequest` emitter | RT | Reject self-computed receipt |
| I-22 | W1/W2 updates cannot mutate `Mandate`, `MandateEnvelope`, `StandingMission` or capability grants | RT | Reject |
| I-23 | A single `instance_id`/`version` cannot both produce a `SrlRelevanceAssessment`/`ProposedGoal` and emit the authority record that accepts it | RT | Reject |
| I-24 | `SrlRelevanceAssessment` rejects any smuggled `capability_grant`, `action_permit` or `action_receipt` field | V1 | Reject |
| I-25 | Cross-restart replay of an event with the same `dedupe_key` is idempotent and does not spawn duplicate work | RT | Idempotent no-op |

## 6. C7 and authority boundary

- **C7 is non-writable and non-bypassable.** No model, generated code or SRL organ holds final execution authority.
- **Separation of powers:** The event ledger, world-state assembler, relevance assessor, portfolio proposer, organ scheduler and outcome acceptor must have independently versioned ports. No single port may both produce evidence and accept it.
- **Non-erasable audit:** Every transition from event → assessment → proposed goal → task → outcome → W1/W2 update must be recorded with digests, timestamps and authority references.
- **Permission ceiling:** The Mandate envelope defines the maximum authority. The system may narrow it internally (e.g., refuse a disposition because of budget), but never widen it.

## 7. Failure modes and fail-closed behavior

| Condition | System behavior |
|---|---|
| Unknown relevance disposition | Treat as `ABSTAIN`; log; do not act |
| Assessor policy digest mismatch | Reject assessment; emit `HELP` if repeated |
| Provider invocation receipt mismatch | Reject assessment; increment help/burden metrics |
| Missing trigger event/gap | Reject assessment |
| Standing mission parent digest mismatch | Reject mission; stop work for that mandate |
| Duplicate event | Deduplicate or reject; never spawn duplicate work |
| Wake/query budget exceeded | Stop binding; emit `HELP` or `REVOCATION_REQUEST` |
| Help budget exceeded | Set `HELP_BURDEN_EXCEEDED`; stop claiming reduced load |
| Help response is not typed authority | Ignore; continue only `continuable_work` if safe |
| Outcome evaluator returns `INVALID` | Do not update mission/learning; log; escalate if pattern |
| C7 check fails | Halt affected action; record non-erasable evidence |

## 8. Test and bypass plan

Before any SRL Runtime code is admitted, the following test classes must exist and fail if bypassed:

1. **Contract-level RED tests** for every invariant in §5, using only the Pydantic contracts.
2. **Adapter-level RED tests** that construct events/assessments and attempt to drive the existing Task/Run/Action spine directly; verify rejection.
3. **Budget exhaustion tests** for wake, query and help budgets.
4. **Replay/deduplication tests** across restart and rehydration.
5. **Authority separation tests** that verify no single component can both produce and accept evidence for the same transition.
6. **Outcome-truth coupling tests** that verify SRL updates consume only trusted evaluator output.
7. **C7 bypass tests** that attempt to disable or override C7 from within an SRL organ.

## 9. Relation to current contracts

The V0 contracts in `packages/contracts/src/agent_os_contracts/mandate.py`, `srl_environment.py` and `srl_help.py` encode the static shape of the objects in this threat model. They do **not** implement the invariants above.

### V0 contracts already enforce
- `Mandate.ratified_at` presence for `RATIFIED`/`ACTIVE` status (I-1).
- Non-empty `MandateEnvelope.allowed_task_classes` / `allowed_effect_classes` (I-2).
- `AgentInstanceRef` does not carry mission/permission/environment/learning fields (I-3).
- `StandingMission.parent_mandate_digest` exists as a field; Runtime must enforce the match (I-4).
- `SrlEnvironmentEvent` carries no disposition/task/capability fields (I-5).
- `SrlRelevanceAssessment` requires a trigger event or gap (I-6).
- `SrlHelpRequest.minimum_answer` and `help_class` validation (I-9, I-10).

### V1 contract amendments required before Runtime
- `SrlRelevanceAssessment` needs: `assessor_policy_digest`, `provider_invocation_receipt_digest`, `proposed_goal_statement`, `minimum_external_input`, `proposed_task_class`, plus validators tying them to disposition.
- `StandingMission` needs: `correction_epoch` and `ratification_receipt_digest` to support W4 version switching.
- A typed help-response wrapper (e.g., `SrlHelpResponse`) is needed to distinguish raw text from `OperatorDecision`/`CapabilityGrant` authority records.
- A `ProposedGoal` / `TaskDraftProposal` contract is needed to separate assessment from activation.

### Runtime-only enforcement
- Mandate status/expiry checks (I-16).
- Environment binding budget, deduplication and write-capability checks (I-12, I-13, I-18, I-25).
- Help burden accounting and separation of receipt computation (I-11, I-20, I-21).
- Authority separation between proposer and acceptor (I-23).
- Outcome-truth coupling via trusted evaluator registry (I-15).
- W1/W2 confinement (I-22).
- Rejection of smuggled authority fields (I-24).

## 10. Non-claims

- This document does not prove that SRL reduces operator hidden cognitive work.
- It does not authorize provider calls, model training, production deployment, main merge or release.
- It does not establish autonomy, general intelligence or product-market fit.
- Contracts exist; Runtime enforcement does not.

## 11. Review and next gates

1. ~~Independent review of this threat model and the contract files.~~ Completed 2026-07-16: `CONDITIONAL_APPROVE` with P0 contract-traceability gaps (see `A-SRL-1-threat-model-review.md`).
2. **Current:** Revise threat model to close P0/P1 findings and clarify V0/V1 boundary.
3. V1 contract amendments for the fields listed in §9.
4. Re-review of amended contracts and updated threat model.
5. Frozen R-SRL-1 preregistration that references these invariants.
6. Implementation cast with RED tests for every invariant.
7. Independent review of the implementation before any result-bearing run.
