# Goal Card + CP/AB + CTO gate — P0-3 INCREMENT 3: W1/W2 OUTCOME CONSUMER

> Status: `CTO_GATE_GRANTED_2026-09-16 / IMPLEMENTED / PENDING_INDEPENDENT_EXACT_DIFF_REVIEW`
> Track: product / translational. Base: `origin/main` @ `f77b9912`.
> Authority refs: A-SRL-1 I-22 / AC-14; P0-3 closed-loop packet §3–§6.
> Claim ceiling: no Alpha / Autonomy(S,E,O,V,T) / release.

## 1. Goal Card

**Problem.** `OutcomeLearningGate` (Inc2) is merged but had **no runtime consumer** — the
SRL closed loop was broken at the last hop (verified: `grep` found it only in the module,
exports and tests; CURRENT_STATE: "No ... W1/W2 outcome consumer ... exists").

**Target U/P.** U: a VERIFIED outcome actually updates the agent's bounded working state
(W1), and nothing else. P: a fail-closed `W1W2OutcomeConsumer` that (a) calls the
unchanged gate, (b) on ADMITTED applies a bounded, deterministic, in-envelope update,
(c) on refusal mutates nothing, and (d) is structurally unable to mutate
Mandate/envelope/grants (I-22).

**Non-goals.** No authority spine; no Mandate/Envelope/StandingMission/grant/policy
mutation; no C7 write; no capability dispatch; no effectiveness claim; default-off.

## 2. What was implemented

- `packages/os_core/src/agent_os_core/w1w2_consumer.py`:
  - `W1State` — typed working state containing **only** `weights` (attention/confidence
    keyed by candidate); structurally has no Mandate/Envelope/grant/policy field (I-22).
  - `W1W2OutcomeConsumer.consume(task_id, outcome)` — calls `OutcomeLearningGate.admit`;
    a refusal returns `REFUSED` with **zero mutation**; an admitted outcome moves the
    candidate weight a fixed step toward the verified score (deterministic, clamped
    `[0,1]`, `0.5 -> 0.75` for score 1.0), and records a durable `W1W2_UPDATED` event
    binding `outcome_id`, `candidate_key`, `w1_before_digest`, `w1_after_digest`, `run_id`.
  - **Durable idempotency**: a repeated `outcome_id` (even via a fresh consumer) is
    `DUPLICATE` with no second event.
- `contracts/runtime.py`: additive `TaskEventType.W1W2_UPDATED`.
- `task_aggregate.py`: the audit marker is a no-op (no aggregate state).
- `apps/api_server/app.py`: `w1w2_learning_enabled: bool = False` (default-off) and the
  composition-root entry `consume_outcome_for_learning(task_id, outcome)` (raises when
  disabled).

## 3. Gate conditions (granted)

| # | Condition | Result |
|---|---|---|
| G1 | Mutates ONLY `W1State`; no Mandate/envelope/grant/policy change (I-22/AC-14) | `test_admitted_outcome_updates_only_w1state`, `test_update_cannot_derive_a_mandate_envelope` |
| G2 | Refusal = zero mutation + typed reason | `test_refused_admission_produces_no_mutation` |
| G3 | Deterministic + idempotent per outcome | `test_update_is_deterministic_and_idempotent_per_outcome` |
| G4 | Durable digest-bound audit event | `test_update_records_digest_bound_audit_event` |
| G5 | Model narration / stale outcome never consumed | `test_model_narration_or_stale_outcome_is_never_consumed` |
| G6 | Default-off at the composition root; no C7/permit change | `test_consumer_is_default_off_at_the_composition_root` |

## 4. Verification

- `tests/product/test_w1w2_outcome_consumer.py` (7) pass; Ruff clean; pyright 0 on
  changed files (only the 2 pre-existing app.py `key_source` errors remain).
- Full `tests/product` regression recorded in the commit message.

## 5. Residual / honesty

- The live end-to-end loop (event -> assessment -> draft -> activation -> outcome ->
  **consume**) is proven at the unit/integration level here (gate + consumer over a real
  golden-path VERIFIED outcome); a production organ that calls
  `consume_outcome_for_learning` automatically remains a later wiring slice, and the
  consumer is default-off.
- Independent exact-diff review still required before promotion.
