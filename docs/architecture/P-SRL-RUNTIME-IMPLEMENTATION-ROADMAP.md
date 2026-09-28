# P-SRL Runtime Implementation Roadmap

> Status: `ROADMAP / REVISE_ACCEPTED / M1_NOT_READY`
> Updated: 2026-07-17
> Scope: Engineering plan to turn Mandate-driven Situated Responsibility Loop into runtime capability.
> Non-claim: This file does not assert autonomy, production readiness, Product Alpha, or M1 implementation readiness.

## 1. Target

Build the smallest product runtime that can accept a ratified Mandate, observe authenticated environment events, decide whether the event matters, emit a non-executing TaskDraft or HelpRequest, activate work only through existing authority/capability gates, evaluate outcome truth, and update knowledge only through verified outcome admission.

The corrected target loop is:

```text
RatifiedMandateRef
  -> authenticated EnvironmentEvent
  -> EnvironmentBindingAuthorization + tenant/workspace/principal scope
  -> SituatedWorkingSetReceipt
  -> SituatedAssessmentRecord
  -> DispatchDecision(disposition, method, reason_codes, budgets)
  -> TaskDraft | HelpRequest | NoProposal
  -> TaskActivationGate
  -> TaskService / WorkflowGraph / ExpectedOutcome
  -> ActionContract / PolicyKernel / CapabilityBroker
  -> Effect
  -> ObservedOutcome
  -> OutcomeLearningGate
  -> Knowledge or Method candidate
```

`TaskDraft` is not an effect. `TaskActivation` is a separate authority transition.

## 2. Pre-M1 gates

### M0a: P-SRL-EVENT-CONTRACT-1

Status: `REQUIRED_BEFORE_M1`

Define:

- `EnvironmentEvent` typed contract;
- event source identity and authentication;
- event idempotency and replay key;
- raw payload redaction boundary;
- tenant/workspace/principal scope;
- Mandate-to-binding resolver;
- multi-Mandate conflict behavior;
- unauthorized, stale, revoked and epoch-changed failure paths.

Exit gate:

- unauthorized binding is rejected;
- duplicate event replays idempotently;
- trace never stores raw secrets;
- a Mandate cannot observe an event outside its authorized environment binding.

### M0b: P-SECURITY-BOUNDARY-0

Status: `REQUIRED_BEFORE_M1`

Define the minimum local-to-pilot security model:

- tenant-scoped mandates and bindings;
- credential lease scope and non-disclosure in traces;
- least-privilege capability grants;
- trace redaction;
- source forgery rejection;
- policy/correction epoch dominance.

Exit gate:

- `test_mandate_steward_rejects_event_from_unauthorized_binding`;
- `test_trace_does_not_leak_secret_payload`;
- `test_revoked_mandate_reused_in_assessment_fails_closed`.

### M0c: P-SRL-E2E-FALSIFIER-1

Status: `REQUIRED_BEFORE_M1_FREEZE`

Define the first end-to-end falsifier. It must run after M1-plus and before Dispatch is expanded.

Task set:

- deployment failure detection;
- API breaking change;
- interruption recovery;
- conflicting constraints;
- irreducible human decision;
- noise/decoy event.

Arms:

- user-driven prompt baseline;
- scheduled workflow baseline;
- SRL V0.

Controls:

- matched provider, tools, budget and time;
- hidden scorer;
- drift detection;
- frozen task units;
- no post-hoc threshold moves.

Metrics:

- user prompts required;
- user state corrections required;
- relevant issues discovered;
- false-positive task creation rate;
- missed critical-event rate;
- useful HelpRequest ratio;
- verified outcomes;
- cost and latency.

Exit gate:

- SRL V0 must reduce hidden cognitive work without worse safety, cost or verified-outcome rate than named baselines.

## 3. M1-plus: MandateSteward V0

Status: `NEXT_BUILD_AFTER_M0a_M0b_RED_TESTS`

Implement:

- `MandateSteward.observe_event(...)`;
- active Mandate and binding resolution;
- `SituatedWorkingSetAssembler.assemble(...)` over Mandate, event, outcome/commitment, projection, evidence/belief/procedure refs, correction epoch and budgets;
- immutable working-set selection receipt with included/excluded reason codes, mandatory missing refs, staleness/conflict markers, compiler version, budgets and replay digest;
- `SituatedAssessmentRecord` creation;
- `TaskDraft`, `HelpRequest`, or `NoProposal` emission;
- duplicate event idempotency;
- pause/revoke/correction dominance;
- structured trace and cost/SLO emission.

Strict non-goals:

- no direct external effects;
- no Task activation without `TaskActivationGate`;
- no capability invocation;
- no self-modification;
- no cross-domain learning claim.

Working-set boundary:

```text
RatifiedMandateRef + authenticated event + persistent typed refs
  -> deterministic scope/freshness/authority filter
  -> optional provider retrieval/ranking proposal
  -> immutable SituatedWorkingSetReceipt
  -> relevance/assessment
```

- no raw full-history prompt stuffing as a substitute for memory;
- no second truth or authority store;
- model narration cannot override mandatory inclusion, provenance, staleness, conflicts, missing state or scope;
- budget exhaustion preserves mandatory state and emits typed degradation, `ABSTAIN` or `HELP`;
- missing Mandate/commitment/ExpectedOutcome/authority/evidence required by the consumer prevents `READY`.

TaskDraft boundary:

```text
TaskDraft
  -> not scheduled
  -> not executable
  -> cannot call connectors
  -> cannot create ActionContract
  -> must bind proposed Goal/Commitment/ExpectedOutcome/WorkflowGraph before activation
```

TaskActivation requires:

- policy/capability gate;
- authority scope;
- frozen ExpectedOutcome;
- failure path;
- evidence requirements;
- correction epoch check.

Initial local SLOs:

- p99 `observe_event -> TaskDraft/HelpRequest/NoProposal` <= 30 seconds in local controlled slice;
- provider/model budget <= 50k tokens per event assessment;
- false-positive task creation rate <= 20% on held-out M0c units;
- zero unauthorized activation.

Exit gate:

- authorized event can create a non-executing TaskDraft;
- unauthorized, stale, revoked or changed-epoch mandate fails closed;
- duplicate event returns the same persisted assessment result;
- identical sources/compiler version replay the same working-set digest, while source/version drift changes identity;
- unauthorized, secret-bearing, stale-unmarked or cross-tenant inputs cannot enter the working set;
- conflicts remain explicit and mandatory missing state yields `ABSTAIN` or `HELP`;
- TaskDraft cannot activate or invoke connectors without TaskActivationGate;
- trace includes cost, latency, policy reason codes and redacted payload evidence.

## 4. P-SRL-DISPATCH-1

Status: `AFTER_M1_PLUS`

Replace separate M2 and M3 with one dispatch decision:

```text
(event, mandate, state, evidence, open commitments, budget)
  -> DispatchDecision(
       disposition,
       method,
       reason_codes,
       score_inputs,
       budgets,
       help_request?
     )
```

Disposition:

```text
IGNORE | OBSERVE | INVESTIGATE | CREATE_DRAFT | HELP | ABSTAIN | PARK
```

Method:

```text
PLAN_FIRST | EXPLORE_FIRST | ALGORITHM_FIRST | HYBRID_LOOP | ADAPTER_TO_DATA_AGENT | NONE
```

Required machine-checkable fields:

- impact score;
- urgency score;
- uncertainty/evidence-gap score;
- authority status;
- reversibility/risk;
- data readiness;
- causal identifiability status;
- cost estimate;
- selected baseline/falsifier.

Falsifiers:

- all-events-create-tasks;
- random disposition;
- prompt-only planner.

Exit gate:

- deterministic score must cross threshold before `CREATE_DRAFT`;
- model narration cannot satisfy score/evidence fields;
- missing data grain routes to `EXPLORE_FIRST` or `HELP`;
- causal/predictive/optimization claims require algorithm/statistical path or `HELP`;
- Data Agent analytical paths are adapted where available instead of reinvented.

## 5. P-SRL-PILOT-1

Status: `AFTER_M1_PLUS_AND_INITIAL_DISPATCH`

Run a controlled local pilot for 1-2 weeks on one real repository/project lane.

Measure:

- HelpRequest usefulness;
- false-positive draft rate;
- missed-event rate;
- operator corrections;
- verified outcomes;
- cost/latency;
- unsafe or unsupported attempts.

Purpose:

- calibrate Dispatch;
- decide whether MethodSelector complexity is justified;
- prevent speculative infrastructure buildout.

## 6. Knowledge path

### M4a: hand-seeded knowledge assets

Status: `AFTER_M1_PLUS`

Seed 5-10 reviewed `Rule`, `Procedure`, and `Case` assets. Do not auto-generate knowledge yet.

### M4b: measure knowledge usefulness

Status: `AFTER_M4a`

Compare outcomes with and without seeded assets on held-out tasks.

### M4c: automatic candidate generation

Status: `AFTER_M4b_POSITIVE`

Only verified, scoped, evidence-bound outcomes admitted by `OutcomeLearningGate.admit(...)` may produce candidates or raise confidence.

Exit gate:

- invalid/unresolved outcomes cannot update confidence;
- cross-task default behavior changes require W3/W4 promotion;
- bad assets can be downgraded, revoked and excluded from future dispatch.

Memory/consolidation boundary:

- event/evidence remains separately retained and auditable;
- episodic Task/Run traces may be replayed but do not become reusable knowledge by frequency alone;
- semantic/procedure/world-model/model-update consolidation requires recurrence, counterexamples, outcome attribution, applicability, staleness horizon and cost;
- forgetting changes validity, retrieval priority, retention or decision influence under policy; it cannot silently erase evidence/audit;
- cross-task reader, retention, influence or default-behavior changes enter W3/W4.

## 7. Evolution path

### M5a: W1/W2 direct adaptation

Status: `AFTER_M1_M4_STABLE_TRACES`

Implement online state updates and in-envelope strategy adaptation:

- local belief/task-state updates;
- approved tool/model/workflow selection inside authority envelope;
- outcome-recorded routing changes;
- no permission expansion.

### M5b: W3/W4 candidate promotion

Status: `DEFERRED`

Shadow evolution and atomic promotion start only after M1-M4 produce stable traces and W1/W2 limitations are measured.

Exit gate:

- shadow candidate cannot affect active task;
- independent evaluator and promoter identity are enforced;
- canary/rollback/version pinning exists;
- no self-approval.

## 8. Do not start yet

Do not start these until M1-plus and Dispatch have tested integrated paths and M0c has a first run:

- `P-MULTIMODAL-IR-1`;
- `P-DISTRIBUTED-RUNTIME-1`;
- `R/P-MODEL-TRAINING-LOOP-1`;
- generic `P-DOMAIN-ADAPT-1`.

Domain work is narrowed to `P-DOMAIN-PRIOR-INGEST-1` until product evidence justifies generic domain-model generation.

## 9. Verification matrix

`P-SRL-RUNTIME-VERIFICATION-MATRIX.md` is the binding implementation bridge for this roadmap. It defines first failing tests, implementation entries, evidence artifacts, baselines/falsifiers and pass gates.
