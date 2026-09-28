# Task Packet — P0-3 INCREMENT 3: W1/W2 OUTCOME CONSUMER (SRL closed loop)

> Status: `GOAL_CARD_AND_VERIFICATION_PLAN / AWAITING_CTO_GATE / NO_IMPLEMENTATION_AUTHORITY`
> Track: product / translational. primary_class: P, secondary_class: A.
> Authority refs: `docs/architecture/A-SRL-1-threat-model-and-authority-invariants.md` (I-22, AC-14),
> `.agent_runs/priority-execution-20260913/P0-3-srl-closed-loop-1.md` §3–§6.
> Base: `origin/main` @ `6d618bd7`. Claim ceiling: no Alpha / Autonomy(S,E,O,V,T) / release.

## 1. Goal Card

**Problem.** P0-3 Increment 1 (execution bridge) and Increment 2 (`OutcomeLearningGate`)
are merged, but `OutcomeLearningGate` has **no runtime consumer** (verified: `grep` finds
it only in the module, `__init__` exports and the tests). So the SRL closed loop is
broken at the last hop: a VERIFIED, evidence-bound outcome is *admissible* but nothing
consumes the admission. CURRENT_STATE is explicit: "No ... W1/W2 outcome consumer ...
exists".

**Target U/P.** U: a verified outcome actually updates the agent's bounded working state
(W1 attention/working-set tactics) and/or candidate strategy selection (W2), and nothing
else. P: a fail-closed `W1W2OutcomeConsumer` that (a) calls the gate, (b) on ADMITTED
applies a bounded, deterministic, auditable in-envelope update, (c) on refusal mutates
nothing, and (d) is *provably* unable to mutate Mandate/envelope/grants (I-22).

**Non-goals.** No new authority spine; no Mandate/envelope/StandingMission/grant/policy
mutation; no C7 write; no ProviderProfile selector; no external backend activation; no
autonomy/effectiveness claim; no research-track change. W1/W2 updates are restricted to
**in-envelope tactics only** (sensing cadence, query order, model/tool selection,
retry/threshold strategy and attention/confidence weights).

## 2. Context Pack (verified at origin/main 6d618bd7)

- `OutcomeLearningGate.admit(task_id, outcome) -> OutcomeAdmissionDecision`
  (`packages/os_core/src/agent_os_core/outcome_learning_gate.py`): fail-closed, read-only;
  admits only a VERIFIED, evidence-bound, currently-trusted outcome; never mutates state.
- `TaskService.current_outcome` / `record_outcome` / `validated_test_report` (evaluator
  registry) — the outcome truth path.
- A-SRL-1 invariant **I-22**: W1/W2 updates must not mutate `Mandate`, `MandateEnvelope`,
  `StandingMission` or capability grants. **AC-14** requires a RED test that a W1/W2
  update cannot derive a new envelope, and that it is rejected.
- Non-erasable audit: every event → assessment → proposed goal → task → outcome →
  W1/W2 update must be recorded with digests, timestamps and authority refs.
- Existing working-set / relevance surfaces: `relevance.py` (ProviderRelevanceAssessor),
  `mandate_steward.py`, `proposal_engine.py` — reference points, not to be restructured.

## 3. Architecture Brief

```text
ObservedOutcome (task terminal truth)
  -> OutcomeLearningGate.admit(task_id, outcome)          # existing, unchanged
       refused -> NO-OP (return the typed refusal; zero mutation)
       admitted -> W1W2OutcomeConsumer.consume(decision, task_id, outcome)
             -> deterministic in-envelope W1 update (typed W1State, no envelope fields)
             -> durable W1W2_UPDATED event (digests + timestamps + authority refs)
```

- New: `W1State` (typed, **contains only in-envelope tactic fields** — attention/
  confidence weights keyed by candidate; structurally has no Mandate/envelope/grant
  field), `W1W2OutcomeConsumer`, and an additive audit event.
- The consumer is a **pure function of (admitted decision, outcome, current W1State)**:
  deterministic, idempotent per `observed_outcome_id`, and cannot invent authority.
- Consumption is **opt-in and default-off** at the composition root (a wiring slice),
  matching how the mid-window freeze treats new runtime consumers.

## 4. CTO gate conditions (for this packet)

| # | Condition | Class |
|---|---|---|
| G1 | The consumer mutates ONLY `W1State`; a runtime test proves no Mandate/envelope/StandingMission/grant/policy object changes (I-22 / AC-14) | P/A |
| G2 | Fail-closed: a refused admission produces zero mutation and a typed reason | P |
| G3 | Deterministic + idempotent per `observed_outcome_id` (replay records one update) | E |
| G4 | Durable audit event binds outcome digest, W1 before/after digest and authority refs | P/A |
| G5 | End-to-end: the full loop runs on 1 held-out unit; unauthorized activation = 0 | P |
| G6 | No C7/permit/permission-matrix change; default-off wiring | A |

Kill metric: any mutation outside `W1State`; any admission consumed without a verified
current outcome; any non-deterministic/non-idempotent update.

## 5. First failing tests (RED, bypass-detecting — must fail before implementation)

```
tests/product/test_w1w2_outcome_consumer.py
  test_refused_admission_produces_no_mutation
  test_admitted_outcome_updates_only_w1state            # I-22 / AC-14 confinement
  test_update_cannot_derive_a_mandate_envelope          # AC-14
  test_update_is_deterministic_and_idempotent_per_outcome
  test_update_records_digest_bound_audit_event
  test_model_narration_or_stale_outcome_is_never_consumed
  test_consumer_is_default_off_at_the_composition_root
```

Each must fail if the consumer returns constant success, consumes an unverified outcome,
mutates an out-of-envelope object, or double-applies a replayed outcome.

## 6. Authority boundary

- This packet authorizes nothing. Implementation needs **CTO gate** on G1–G6, then
  test-first, then an independent exact-diff review and a promotion window.
- I-22 is non-negotiable: a W1/W2 update may never widen Mandate/envelope/grants; if the
  design cannot confine the update surface structurally, the slice is `REVISE_TO_SPEC`.
- No C7/permit change; the consumer never executes an effect or dispatches a capability.
