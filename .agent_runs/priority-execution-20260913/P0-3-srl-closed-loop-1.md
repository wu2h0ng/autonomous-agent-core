# Task Packet — SRL-CLOSED-LOOP-1

> Status: `GOAL_CARD_AND_VERIFICATION_PLAN / RECOMMEND_ONLY / NO_IMPLEMENTATION_AUTHORIZATION`
> Track: product
> primary_class: P  secondary_class: A/E
> Portfolio lane: PRIMARY_PRODUCT_LOOP
> Depends on: P0-2 G1 (pinned truth); optional P0-1 G3 (ExpectedOutcome supply)
> Authority: `docs/architecture/P-SRL-RUNTIME-1-design-2026-07-16.md`, `docs/architecture/P-SRL-RUNTIME-VERIFICATION-MATRIX.md`, `docs/architecture/A-SRL-1-threat-model-and-authority-invariants.md`, `docs/architecture/P-SRL-RUNTIME-ROADMAP-ENGINEERING-REVIEW-2026-07-16.md`

## 1. Goal Card

**Problem.** The SRL loop is integrated only through its perception/accounting half (Mandate input, environment binding, active perception, read-only responsibility view, Outcome Portfolio settlement, HelpRequest/Response). `TaskActivation`, capability grant and Dispatch remain literal false. The system can *observe and record* but cannot *decide and activate* bounded work, so it cannot yet produce the M2 evidence the product loop exists to produce.

**Target U.** A principal ratifies a Mandate and an EnvironmentBinding; on an authorized event the system assesses relevance and either (a) emits a non-executing TaskDraft that, after an explicit authority transition, activates exactly one bounded Task through the existing authority spine, or (b) emits a structured HelpRequest. No operator needs to reconstruct state or the next step.

**Non-goals (strict).**
- No Dispatch breadth (method selection), no `P-DISTRIBUTED-RUNTIME-1`, no multimodal, no training, no domain-adaptation engine.
- No production activation, no automatic wake beyond the existing bounded active perception, no promotion.
- No autonomy / HCW-superiority / release claim from this slice.

## 2. Context Pack

- `packages/contracts/src/agent_os_contracts/{mandate,srl_environment,srl_help}.py`
- `packages/os_core/src/agent_os_core/{task_service,execution,governance,capability}.py`
- `apps/api_server/`, `apps/cli/__main__.py` (entry surfaces; **do not restructure surfaces in this task**)
- Existing `MandateTaskLink` + responsibility projection implementation.
- Related live worktree: `codex/working-set-context-measure-20260913` (Situated Working Set). Do not co-write; consume its output only after review.

## 3. Contracts to add

| Contract | Responsibility | Must not become |
|---|---|---|
| `TaskDraft` | non-executing proposal binding proposed Goal/Commitment/ExpectedOutcome/WorkflowGraph refs | executable work or connector caller |
| `TaskActivationGate` | the single authority transition draft -> Task | a second authority spine |
| `TaskActivation` | durable activation record (policy decision, capability scope, C7 epoch, expected-outcome digest) | mutable grant |
| `DispatchDecision` (minimal) | disposition + reason codes + budgets | narrative justification |
| `OutcomeLearningGate.admit(...)` | admit only verified, scoped, evidence-bound outcomes to W1/W2 | confidence update from UNRESOLVED |

## 4. First failing tests (must fail before implementation; bypass-detecting)

```
tests/product/test_srl_runtime_invariants.py
  test_mandate_steward_cannot_activate_task_without_policy_gate
  test_task_draft_does_not_call_external_connectors
  test_task_activation_requires_expected_outcome_and_commitment
  test_mandate_binding_epoch_dominates_pending_drafts
  test_revoked_or_epoch_changed_mandate_fails_closed
  test_duplicate_event_replays_same_assessment

tests/product/test_srl_runtime_outcome.py
  test_learning_rejects_unresolved_outcome
  test_model_narration_does_not_satisfy_evidence_requirement
  test_unauthorized_activation_is_literal_false
```

Test validity rule: each test must fail if the implementation returns constant success, accepts model narration as evidence, or bypasses policy/authority/C7 epoch.

## 5. Minimal end-to-end unit

```text
authorized EnvironmentEvent
 -> relevance assessment (existing)
 -> TaskDraft (non-executing)
 -> TaskActivationGate: PolicyKernel + CapabilityBroker + ExpectedOutcome + C7 epoch
 -> existing RunCoordinator executes 1 allowlisted unit of work
 -> Outcome truth verdict
 -> commitment/portfolio settlement (existing)
 -> W1/W2 record  OR  HelpRequest
```

## 6. Gates

| Gate | Exit condition | Class |
|---|---|---|
| G1 scope freeze | exactly one vertical unit; no breadth | A |
| G2 RED in place | 9 tests exist and fail pre-implementation | E |
| G3 draft is inert | draft cannot build ActionContract / call connector | P/A |
| G4 activation gate | fails closed without policy + capability + ExpectedOutcome + C7 epoch | P/A |
| G5 end-to-end | the loop above runs; 1 held-out unit; zero unauthorized activation | P |
| G6 baseline | vs user-prompted and scheduled arms on HCW + verified outcome, local controlled slice only | R/P |
| G7 independent review | P0=0/P1=0, builder_id != reviewed_by, exact-head evidence | E |

**Local SLO:** p99 observe -> draft/help <= 30s; <= 50k tokens/event assessment; false-positive draft rate <= 20% on held-out units.

## 7. Authority and claim boundary

- Implementation requires a CTO gate; this packet is not that gate.
- No push/merge/release; no production activation; no autonomy/HCW claim.
- C7 remains external and non-bypassable; TaskActivation only *consumes* the existing authority spine.
- Status may only be reported as specified/implemented/tested/integrated; `verified` needs independent review.

## 8. Open decisions (for the CTO gate)

1. Does the first `TaskDraft` carry a full WorkflowGraph draft, or only goal + capability requirements (graph left to AWL)?
2. Is instance-id/version separation sufficient for I-23, or does the Assessor need process isolation from day one?
3. Which persistence backs `EventLedgerPort`/`AuditPort` (`persistence.py` / `postgres.py` / `event_store.py`)?
4. Does the slice consume P0-1's predicate `ExpectedOutcome`, or start with the deterministic pytest evaluator and integrate predicates later?
