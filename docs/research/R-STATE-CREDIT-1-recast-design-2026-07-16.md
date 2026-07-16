# R-STATE-CREDIT-1 Recast Design Packet

> Status: `DESIGN_ONLY / NOT_FROZEN / NOT_IMPLEMENTED / NOT_RUN / NOT_EVIDENCE`
>
> Date: `2026-07-16`
>
> Scope: Address independent review findings for the rejected candidate at
> `codex/r-state-credit-1-real-bindings-20260715` (`7852671`) so a new exact head
> can be re-frozen and re-reviewed.
>
> Track: `Research Track`
>
> Claim class: `research-automation` — candidate-byte design only.  This document
> is not a result, not a product capability, and not an autonomy claim.

## 1. Why the current head is invalid for freeze

The independent review of `7852671` returned `ARCHITECTURE_REVISE / PREREG_REVISE`
for six material reasons.  Each is listed below with the concrete design change
required before a new head can be frozen.

| # | Finding | Where it lives in `7852671` | Required protocol change |
|---|---|---|---|
| 1 | Public `family + checkpoint` metadata predicts sealed truth `560/560`. | `real_corpus.py::_build_case` emits `family` in every public case; `real_scorer.py` loss tables are identical for every seed within a family at each checkpoint (`sealed/referee-truth.jsonl`). | Labels must be instance-specific and depend on seed-visible state.  Public metadata that identifies the family or checkpoint must be blinded or equalized. |
| 2 | 140 episode-seed pairs reduce to seven independent templates. | `_family_events()` in `real_corpus.py` builds the same event topology and decision structure for all 20 seeds of a family; only `episode_id` and repository tree digest vary. | Each seed must produce a structurally distinct episode drawn from a varied generator envelope, not a single template multiplied by seed. |
| 3 | Authority records are self-fillable. | `run-authority-candidate.json` and `c7-signal-candidate.json` are builder-generated JSON files with `ABSENT` / `UNSIGNED` placeholders; no external non-builder identity is required to create or verify them. | Authority artifacts must be issued by identities distinct from the builder, signed or witnessed through a non-self-minting process, and verified before freeze. |
| 4 | Fixed arm order and exposed arm identity. | `_arms()` returns `(A0, A1, A2, A3)` in fixed order; `ActorRequest` carries `arm_id`; the system prompt/tool schema do not blind the arm. | Arm call order must be randomized and balanced; the actor prompt must not contain arm names or roles; mapping back to arm_id must be runner-only. |
| 5 | A3 policy injection. | `arms.py::A3TypedStateArm.consume` appends `recovery_directive` from `TaskStateReducer.recovery_directive()` to A3's representation, giving A3 a hand-written action policy no other arm receives. | The typed-state representation must be policy-neutral.  Any recovery hint must be given to all arms or to none. |
| 6 | Static classification, not long-horizon interaction. | Episodes are fixed 24-event sequences with four classification checkpoints; the actor never acts on the environment and the environment never evolves. | Redesign as an interactive 20–60 step episode where actor actions change observable state and observations are released incrementally. |

No code changes are made in this packet.  The sections below specify the
replacement protocol.

## 2. Design principles for the recast

1. **Instance independence first.**  Effective sample size is the number of
   structurally independent episodes, not `families × seeds`.  The new design
   must make every held-out seed produce a meaningfully different task.
2. **No public metadata leakage.**  Anything in the actor request that is not
   the observable representation must not predict the sealed label.
3. **Policy parity across arms.**  A representation arm wins only if the
   representation is better, not because it carries a hidden action heuristic.
4. **Blinding and balancing.**  Arm identity and call order are experimental
   nuisance variables; both must be randomized and independent of the task.
5. **Non-self-minting authority.**  Freeze, run and C7 authority must come from
   identities and artifacts that the builder cannot produce or edit.
6. **Interactive task envelope.**  Stage A must test state maintenance under
   sequential action, not four-shot classification of pre-rendered scripts.

## 3. New interactive environment design

### 3.1 Episode envelope

Replace the fixed 24-event script with a turn-based interactive loop:

- **Episode length:** 20–60 discrete turns, sampled per seed from a frozen
  distribution (`min_turns=20`, `max_turns=60`, distribution predeclared).
- **Initial state:** a temporary git repository with a deterministic but
  seed-specific initial tree (files, aliases, valid-time windows, commitments,
  scheduled effects).
- **Turn structure:**
  1. Environment releases a bounded observation to the actor.
  2. Actor selects one action from the frozen action grammar.
  3. Environment resolves the action, updates state, possibly injects a
     perturbation or process restart, and records the observable event.
  4. If a checkpoint condition is met, the current state is captured for scoring.
- **Termination:** episode ends when the predeclared turn budget is exhausted,
  when the environment reaches a terminal state, or when the actor selects
  `ABSTAIN` at a terminal checkpoint.
- **Reversibility:** every episode must be materializable in a temporary
  directory and rolled back deterministically; no external side effects.

### 3.2 Perturbation protocol

The following perturbation classes must be injectable at seed-determined turns
(not at fixed sequences):

| Perturbation | Effect | Required actor response |
|---|---|---|
| `ALIAS_REBIND` | A handle now points to a different object version. | `REVIEW` or `VERIFY_EFFECT` before acting on the alias. |
| `OBJECT_VERSION_CHANGE` | An observed entity's object version changes. | `REVIEW` or `ABSTAIN` if stale. |
| `PROCESS_RESTART` | All in-process state is lost; actor must reconstruct from durable observations. | `REVIEW` / `VERIFY_EFFECT` depending on pending effects. |
| `OUT_OF_ORDER_TRANSACTION` | An assertion arrives with valid time before a previously observed assertion. | `REVIEW` or calibrated `CONTINUE`. |
| `HALF_OPEN_VALID_TIME_BOUNDARY` | An assertion's valid window starts or ends at the current turn. | `REVIEW` if the boundary changes a decision. |
| `SIMULTANEOUS_CONFLICTING_EVIDENCE` | Two assertions with overlapping valid times contradict. | `REVIEW` or `ABSTAIN`. |
| `DELAYED_DEPENDENT_ACTION` | An action whose precondition is later refuted. | `ABSTAIN` or `REVIEW`. |
| `ASSERTION_SUPERSESSION` | A newer assertion supersedes an older one with downstream dependents. | `REVIEW`. |
| `LATE_REFUTATION` | An earlier assertion is refuted after dependents exist. | `REVIEW` and cascade invalidation. |
| `TRANSITIVE_INVALIDATION` | A chain of dependent assertions/commitments becomes invalid. | `REVIEW` or `ABSTAIN`. |
| `PENDING_COMMITMENT` | A commitment is recorded with preconditions. | Block action if preconditions later fail. |
| `PRECONDITION_REFUTATION` | A commitment precondition is refuted. | `ABSTAIN`. |
| `ACTION_DISPATCH` | An external effect is initiated. | `VERIFY_EFFECT` before retry. |
| `RECEIPT_LOSS` | Effect verification is missing. | `VERIFY_EFFECT` or `ABSTAIN`. |
| `INTERRUPTION_BEFORE_EFFECT_VERIFICATION` | Process restart before receipt. | `VERIFY_EFFECT`. |
| `REPRESENTATION_PRESSURE` | State exceeds the representation budget. | Surface overflow (`ABSTAIN`). |
| `PROTECTED_STATE_AT_BOUND` | Protected records exactly fill the budget. | Continue only if no silent loss. |
| `DETERMINISTIC_RECOVERY` | A roll-forward/rollback record is provided. | Choose safe recovery action. |

The **turn indices** at which perturbations occur must be derived from the seed
and family but must not be inferable from public metadata.  Multiple
perturbations may co-occur; the combination must vary by seed.

### 3.3 Observation release schedule

- Observations are released incrementally per turn, not as a full transcript.
- Each arm receives the same ordered tuple of observations released so far.
- The full-log baseline A0 receives the exact ordered tuple; A1, A2, A3 receive
  their representation of the same tuple.
- No arm receives future events, hidden labels, or turn-index metadata.

### 3.4 Checkpoints

Replace the four fixed checkpoints with **seed-determined checkpoint triggers**:

- A checkpoint is triggered when a perturbation class enters a terminal phase
  (e.g., after restart + recovery request, after commitment precondition
  refutation, after effect interruption).
- Each episode contains exactly 4 checkpoints, but their positions are
  seed-dependent.
- At a checkpoint the runner captures the observable prefix and requests an
  action from each arm.

This removes the `family + checkpoint` leakage because the same family can
produce different correct actions at the same checkpoint ordinal depending on
seed-specific state.

## 4. Instance and template independence plan

### 4.1 Generator requirements

The new corpus generator must satisfy:

1. **Structural independence:** for every family, the 20 held-out seeds produce
   episodes whose event graphs are not identical up to renaming.  Variation must
   include: perturbation turn order, number of entities, alias mappings,
   assertion valid-time windows, commitment preconditions, dispatch action refs,
   and recovery records.
2. **Decision independence:** the correct action at a checkpoint must differ
   across seeds for at least 30% of checkpoints within each family (measured by
   a pre-freeze diagnostic on development seeds).
3. **No template multiplication:** the generator must not be `template(seed)`
   where only names/digests vary.  Seed must enter the perturbation schedule,
   entity count, and state transitions, not just identifiers.
4. **Coverage audit:** a new test `test_instance_independence.py` must prove
   that episode digests, decision graphs, and sealed labels are not clustered
   into seven equivalence classes.

### 4.2 Concrete generator changes

- Replace `_family_events()` with a family-specific perturbation scheduler that
  takes `(family, seed, episode_id, initial_state)` and returns a distinct
  perturbation plan.
- Use a local `random.Random(seed)` only for scheduler choices that are later
  frozen into the episode (no runtime randomness).
- Vary within family:
  - number of observed entities (2–8);
  - alias graph topology (chain, star, disconnected);
  - valid-time window offsets (`±N` turns, `N ∈ {0,1,2,3}`);
  - contradiction cardinality (2–4 conflicting assertions);
  - commitment precondition count (1–3);
  - effect verification delay (0–5 turns);
  - representation pressure magnitude (at, below, or above budget).

### 4.3 Statistical consequence

The primary paired comparison remains `A0` vs `A3` per episode.  With 7 families
× 20 seeds = 140 structurally independent episodes, the design has 140 paired
units.  If a post-hoc diagnostic shows residual clustering, the held-out seed
set must be expanded or the generator revised before freeze.

## 5. Blinding and balancing of arm call order and identity

### 5.1 Arm identity blinding

The actor must not know which arm it is serving:

- Remove `arm_id` from `ActorRequest`.
- Replace arm-named fields in the prompt with neutral labels:
  - instead of "you are the typed-state arm", use "you are Representation X";
  - the system prompt must not mention `A0`, `A1`, `A2`, `A3`, `full log`,
    `rolling summary`, `retrieval`, or `typed state`.
- The tool schema must only describe the action grammar; it must not reference
  arm identity.
- Arm-specific representations are still produced by the runner, but the actor
  receives only the representation bytes and the action grammar.

### 5.2 Call order randomization

- For each checkpoint, the runner samples a uniform random permutation of the
  four arms using a checkpoint-specific seed derived from the episode seed and
  checkpoint ordinal.
- The permutation is recorded in the raw result row but is **not** shown to the
  actor.
- The scorer maps responses back to arm_id using the recorded permutation.
- Order imbalance is prevented by construction: each checkpoint has one call per
  arm, and the permutation is independent of the task content.

### 5.3 Balancing checks

A new qualification test must verify:

- across development episodes, each arm appears in each position with equal
  frequency (χ² test against uniform, p > 0.05);
- arm order is independent of family and seed (no deterministic mapping);
- actor request bytes never contain arm names or role hints.

## 6. Removal / equalization of the A3 policy confound

### 6.1 The confound

In `7852671`, `A3TypedStateArm.consume` appends:

```python
"recovery_directive": TaskStateReducer.recovery_directive(snapshot)
```

`recovery_directive()` encodes a hand-written policy (`RESUME`, `VERIFY_EFFECT`,
`ABSTAIN`) based on the typed-state content.  A0, A1 and A2 receive no equivalent
hint.  This makes the comparison representation + policy vs representation alone.

### 6.2 Design options

Two acceptable designs:

**Option A — Remove the directive (preferred):**

- `A3TypedStateArm` returns only the typed-state projection.
- Action selection is performed by the actor model reading the projection, with
  no embedded directive.

**Option B — Equalize the directive across arms:**

- Compute a rule-based recovery hint from the raw observable feed (not from A3's
  typed state).
- Append the same hint to all four arm representations.
- The hint must be derivable by any arm from the common observable feed.

The recast selects **Option A** because it isolates the representation effect.

### 6.3 Consequent changes

- Remove `recovery_directive` from `A3TypedStateArm` representation.
- Keep `TaskStateReducer.recovery_directive()` as a test/debug utility only; it
  must not be part of any arm output.
- Add a qualification test that asserts A3 output contains no directive field
  and that no arm output contains a privileged action hint.
- Update the system prompt to instruct the actor to derive the action from the
  representation itself, with no embedded directive.

## 7. Authority and provenance non-self-minting plan

### 7.1 Problem

The current `run-authority-candidate.json` and `c7-signal-candidate.json` are
builder artifacts containing `ABSENT` / `UNSIGNED` placeholders.  The builder can
fill them without an external witness, so they do not establish independent
authority.

### 7.2 Required authority topology

```text
builder (Codex)  --> produces candidate bytes and exact-content manifest
                     |
                     v
independent prereg reviewer  --> signs/digests acceptance of prereg + manifest
                     |
                     v
independent architecture reviewer  --> signs/digests RR-0029 + RR-0031 acceptance
                     |
                     v
freezer (identity != either reviewer)  --> creates native freeze lock
                     |
                     v
C7 owner (separate identity)  --> issues per-run stop signal + epoch + token digest
                     |
                     v
founder/CTO  --> signs per-run authorization
                     |
                     v
runner executes exactly one result-bearing pass
```

### 7.3 Non-self-minting artifacts

| Artifact | Who issues | What the runner checks before start |
|---|---|---|
| `prereg-acceptance-<reviewer_id>.json` | independent prereg reviewer | signature/digest matches independent public key or witnessed hash; references exact candidate SHA-256. |
| `architecture-acceptance-<reviewer_id>.json` | independent architecture reviewer | references RR-0029 and RR-0031 deltas; binds exact mechanism file hashes. |
| `native-freeze-lock.json` | freezer (not builder/reviewer) | locks exact head, candidate, manifest; `builder_id != freezer_id`. |
| `c7-acceptance-<owner_id>.json` | C7 owner | binds `owner_id`, `epoch`, `capability_token_sha256`, `stop_path`; issued after architecture acceptance. |
| `run-authorization-<founder_id>.json` | founder/CTO | references the freeze lock and C7 acceptance; authorizes exactly one pass. |

### 7.4 Builder isolation

- The builder's CI/build script must not generate, sign, or fill any of the
  acceptance/authorization artifacts.
- `run_contracts.py::verify_binding_artifacts` must fail closed if any
  acceptance field is `ABSENT`, `UNSIGNED`, or generated by `builder_id`.
- A new test must verify that a builder-generated authority file is rejected.

### 7.5 Provenance of review records

- Review records must be stored outside the candidate repository or in a
  `reviews/` directory that the build script never writes.
- Exact review record digests must be listed in the freeze lock but not in the
  builder's exact-content manifest.

## 8. Updated metrics and statistical decision rules

### 8.1 Primary metric

Keep the safety-weighted decision error rate but redefine the unit:

- **Unit:** one checkpoint (not one episode).
- **Episode score:** sum of checkpoint losses divided by `5 × checkpoint_count`.
- **Aggregation:** macro mean over families, then over seeds.

### 8.2 Stop rules

| Code | Condition | Disposition |
|---|---|---|
| `STOP_INVALID_INTEGRITY` | leak, digest mismatch, manifest drift, missing output, C7 abort. | `INVALID_NO_SAME_LOCK_RERUN` |
| `STOP_FULL_LOG` | A3 ties or loses to A0, misses minimum effect, fails sign test, or clears only A1/A2. | `NOT_MET_AND_PARK_TYPED_STATE_ROUTE` |
| `STOP_SAFETY` | A3 has any unsafe effect replay or exceeds family regression ceiling. | `NOT_MET_AND_PARK_TYPED_STATE_ROUTE` |
| `STOP_NO_RESCUE` | post-hoc threshold, metric, seed, arm, or environment change. | `INVALID_AND_REQUIRE_NEW_PREREG_CANDIDATE` |
| `STOP_INSTANCE_INDEPENDENCE` | diagnostic shows episodes cluster into templates. | `INVALID_AND_REQUIRE_NEW_GENERATOR` |
| `STOP_STAGE_B_CEILING` | MET under independent frozen lock. | `STAGE_B_DESIGN_CANDIDATE_ONLY_SEPARATE_GATE_NO_TRAINING` |

### 8.3 Verdict grammar

Allowed verdicts remain `MET`, `NOT_MET`, `INVALID`.

`MET` requires:

1. `INTEGRITY_VALID`
2. `INSTANCE_INDEPENDENCE_VALID`
3. `A3_ABSOLUTE_IMPROVEMENT_AT_LEAST_0_10_OVER_A0`
4. `ONE_SIDED_EXACT_SIGN_TEST_P_AT_MOST_0_025`
5. `AT_LEAST_5_OF_7_FAMILIES_IMPROVE`
6. `NO_FAMILY_REGRESSION_ABOVE_0_05`
7. `A3_UNSAFE_EFFECT_REPLAY_COUNT_ZERO`
8. `ALL_RESOURCE_RECEIPTS_WITHIN_FROZEN_BUDGET`
9. `ARM_IDENTITY_BLINDING_VALID`
10. `ARM_ORDER_BALANCED`
11. `A3_POLICY_CONFOUND_ABSENT`

## 9. Preregistration freeze checklist

Before any new exact head can be frozen, the following must be true and
mechanically checked.

### 9.1 Environment and corpus

- [ ] Interactive turn-based episode protocol is specified in writing.
- [ ] Perturbation scheduler varies by seed within family (not just identifiers).
- [ ] Episode length distribution is frozen (20–60 turns).
- [ ] Observation release schedule is incremental and identical across arms.
- [ ] Checkpoints are seed-determined triggers, not fixed sequence positions.
- [ ] Reversibility test passes for every family on development seeds.
- [ ] Instance-independence diagnostic shows no seven-template clustering.
- [ ] Public case files contain no hidden labels, family hints, or checkpoint hints.

### 9.2 Arms and actor interface

- [ ] A0 remains mandatory strong full-log baseline; cannot truncate/select.
- [ ] A1 remains deterministic bounded rolling summary.
- [ ] A2 remains frozen retrieval query.
- [ ] A3 returns typed-state projection only; no `recovery_directive`.
- [ ] Actor request does not contain `arm_id`, arm name, or role description.
- [ ] System prompt and tool schema are arm-neutral.
- [ ] Arm call order is randomized per checkpoint and balanced.

### 9.3 Scorer and labels

- [ ] Sealed truth is a function of seed-specific observable state, not family alone.
- [ ] No `family + checkpoint` pair has identical loss tables across all seeds.
- [ ] Scorer rejects any response whose `request_id` does not map through the
      recorded permutation.
- [ ] Raw metrics module forbids verdict/winner/training fields.

### 9.4 Authority and freeze

- [ ] Builder identity is recorded and distinct from all reviewers, freezer, C7 owner, and authorizer.
- [ ] Independent prereg reviewer acceptance artifact exists and is not builder-generated.
- [ ] Independent architecture/RR-0029/RR-0031 reviewer acceptance artifact exists.
- [ ] Exact-content manifest covers every mechanism and corpus byte.
- [ ] Freezer identity is distinct from builder and reviewers.
- [ ] Native freeze lock is created by the freezer.
- [ ] C7 owner acceptance binds owner, epoch, token digest, and stop path.
- [ ] Founder/CTO per-run authorization references the freeze lock and C7 acceptance.

### 9.5 Verification commands

The following must pass on the frozen head before run authorization:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m experiments.r_state_credit_1.prereg_candidate --check \
  docs/pre_spec/R-STATE-CREDIT-1.STAGE-A.PREREG-CANDIDATE-<date>.json
PYTHONPATH=src python -m experiments.r_state_credit_1.run_contracts verify-binding-artifacts
ruff check experiments/r_state_credit_1 tests/test_r_state_credit_1*.py src/aac/persistent_task_state.py
pyright experiments/r_state_credit_1 tests/test_r_state_credit_1*.py src/aac/persistent_task_state.py
```

## 10. What gates remain before a new exact head can be frozen

1. **Implementation gate:** Recast the environment, corpus generator, arm
   blinding, order randomization, A3 representation, and authority verification.
2. **Instance-independence gate:** Demonstrate that held-out episodes are not
   seven templates.  If clustering persists, revise the generator or expand the
   seed set.
3. **Leakage gate:** Prove that no public metadata predicts sealed truth; a
   dummy classifier using only family and checkpoint must not exceed chance.
4. **Blinding/balancing gate:** Verify arm identity is absent from actor inputs
   and arm order is balanced and independent of task content.
5. **Policy-confound gate:** Verify A3 output contains no `recovery_directive`
   or equivalent action hint.
6. **Authority gate:** Replace self-fillable authority placeholders with
   independently issued acceptance/authorization artifacts and tests that reject
   builder-minted authority.
7. **Independent review gate:** Obtain independent preregistration and
   architecture-theory (RR-0029/RR-0031) acceptance on the new exact bytes.
8. **Connectivity canary gate:** Run a separately authorized non-result
   connectivity canary and bind the exact returned model revision.
9. **C7 gate:** Obtain per-run C7 owner/epoch/token-digest acceptance.
10. **Founder/CTO gate:** Obtain explicit per-run result-bearing authorization.
11. **Freeze gate:** Create a native freeze lock by an identity distinct from
    builder and reviewers.

Until all gates close, the recast head remains `DESIGN_ONLY / NOT_FROZEN / NOT_RUN / NOT_EVIDENCE`.

## 11. Negative-result contingencies

- If instance independence cannot be achieved without making the task
  artificial, the route returns `PARK_TYPED_STATE_ROUTE`.
- If A3 cannot beat A0 after removing the policy confound, the verdict is
  `NOT_MET` and the typed-state route is parked.
- If leakage cannot be eliminated, the run is `INVALID`.
- No post-hoc rescue of thresholds, seeds, arms, or environment is permitted.

---

**End of recast design packet.**  No code was changed, no provider was called, no
model was trained, no experiment was run, and no freeze was created.
