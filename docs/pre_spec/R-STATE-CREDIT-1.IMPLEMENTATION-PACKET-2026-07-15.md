# R-STATE-CREDIT-1 Stage A Implementation Packet

> Status: `IMPLEMENTED_LOCAL_MECHANISM_ONLY / NOT_FROZEN / NOT_RUN`
>
> Track: `Research Track`
>
> Date: `2026-07-15`
>
> Scope: persistent semantic task-state substrate and Stage A experiment boundary
>
> Explicit exclusions: `NO_TRAINING / NO_RESULT / NO_STAGE_B_WINNER / NO_PRODUCT_RUNTIME_AUTHORITY`

## 1. Problem lock

The target bottleneck is not tool availability. It is that a skilled operator still
acts as a hidden task-state architecture by maintaining object identity, separating
fact from inference, invalidating stale beliefs, remembering pending commitments,
and deciding whether an interrupted external effect is safe to resume.

Text history, retrieved events, rolling summaries, and typed state are competing
representations of the same observed task trajectory. This packet implements only
the typed-state candidate needed to make a later comparison executable. It does
not establish that typed state is better, that a latent state should be trained,
or that persistent state solves long-horizon autonomy.

## 2. Claim class and ceiling

The implementation claim is limited to:

> A deterministic, append-only, typed semantic state reducer exists for hermetic
> software-task research fixtures, with explicit temporal/version semantics,
> dependency invalidation, bounded safe projection, deterministic rehydration,
> and fail-closed handling of ambiguous dispatched effects.

The following claims are forbidden from this artifact:

- no `Autonomy(S,E,O,V,T)` evidence;
- no general intelligence, self-improvement, learning, transfer, or domain
  adaptation evidence;
- no long-horizon reliability or superiority claim;
- no Product Track runtime capability, release, migration, or customer claim;
- no replacement of Product task/event truth, C7, capability authorization,
  approval, receipts, evidence, or recovery contracts;
- no R-STATE-CREDIT-1 Stage A result, winner, or Stage B run authority.

## 3. Stage A comparison contract

Stage A is a representation falsifier. A later preregistration must compare the
following arms on bit-identical observable events and task mutations:

| Arm | Representation | Permitted operation |
|---|---|---|
| A0 | bounded long context | read the ordered raw event/task transcript |
| A1 | rolling summary | read and replace a deterministic-size text summary |
| A2 | event log plus retrieval | query only the common event store through a frozen retrieval contract |
| A3 | typed semantic state | apply and project the reducer implemented by this packet |

All arms must share the same task instances, initial observations, tool responses,
model/checkpoint, decoding policy, action set, step budget, tool-call budget,
wall-clock accounting, and information-release schedule. Context/state byte or
token budgets and overflow behavior must be frozen before a result-bearing run.
No arm may receive an oracle label, hidden entity key, future event, privileged
test result, or human correction unavailable to the others.

At minimum the frozen task battery must expose:

1. alias and object-version drift;
2. valid-time versus transaction-time updates;
3. simultaneous contradictory evidence;
4. supersession/refutation and downstream dependency invalidation;
5. pending commitment blockage;
6. interruption after dispatch but before effect verification;
7. bounded-context overflow and deterministic recovery.

The preregistration must name executable outcomes rather than narrative quality.
Candidate measures include exact state recovery, stale-belief use, duplicate or
unsafe effect rate, commitment consistency, calibrated abstention, recovery
latency, and state/context cost. Exact metrics, aggregation, thresholds, seeds,
and statistical rules are intentionally not set here; setting them after seeing
results would invalidate the comparison.

### Full-log stop rule

The raw long-context arm is a mandatory cheap baseline. If A3 only ties A0 on the
frozen primary decision metric, or its apparent gain disappears under matched
information and resource accounting, the typed-state route is `PARK`. A weaker
summary or retrieval arm cannot rescue a tie with the full-log baseline.

### Batch-2A hermetic development environment

Batch-2A adds a non-result-bearing development environment under
`experiments/r_state_credit_1/`:

- `contracts.py`: closed event, hidden scenario, arm input/output, resource
  budget, and qualification receipt contracts;
- `scenarios.py`: one deterministic `NOT_EVIDENCE` fixture for each of the seven
  required scenario families;
- `arms.py`: A0 bounded full-log, A1 deterministic rolling summary, A2 frozen
  event retrieval, and A3 visible-event-only typed-state adapter;
- `qualifier.py`: replay, matched-information, budget, leak, interface, and
  nonconstant-baseline checks only.

The hidden referee owns expected state and hidden entity keys. Actor-visible
events are a separate closed type and cannot contain future events, answer labels,
hidden keys, oracle reasons, epistemic status labels, or privileged aliases. All
four arms receive the exact same ordered observable-event tuple. A3 may derive a
typed representation only from fields present in that tuple.

Every arm returns the same resource receipt fields: input bytes, deterministic
token proxy, consumed steps, tool calls, and charged wall-clock budget units.
Budget accounting is deterministic; it does not measure live elapsed time. A0 is
the strong raw-log baseline and cannot truncate, summarize, select, or silently
drop observable events. If the common input budget cannot hold the full event
tuple, A0 and the qualifier fail closed with `INPUT_BUDGET_EXCEEDED`. A1 has a
hard output bound, A2 accepts only a frozen query enum, and A3 must surface
`STATE_OVERFLOW` rather than drop protected state.

Batch-2A fixtures and qualifier receipts are `NOT_EVIDENCE`. The Batch-2A arm
surfaces expose no result runner, winner calculation, statistical test, seed
sweep, training path, or result artifact command.

The implemented qualifier returns only the following closed checks:

1. replay determinism;
2. matched observable-event digest and A0 byte fidelity;
3. common resource receipt validity;
4. hidden-referee leak absence;
5. closed typed interfaces;
6. nonconstant representation and nonconstant plumbing action probes.

The action probe is only an anti-constant plumbing sentinel. It is not scored
against hidden truth and cannot become a task-performance measure. Qualification
does not inspect expected outcomes, compute correctness, rank arms, select a
winner, estimate an effect, or perform significance testing.

A1 is a real bounded rolling summary rather than a constant metadata stub: it
keeps recent visible semantic event fields, an explicit compacted-event count,
and a hash chain over the compacted prefix. A2 reports its explicitly omitted
events under one frozen query enum. A3 builds aliases only from visible
`ALIAS_OBSERVED` events, assigns `UNIDENTIFIED` rather than an unseen epistemic
truth label, and derives lifecycle/conflict status only from the common feed.

The mutation battery covers unreleased events and future-event references,
ragged sequences, hidden-referee values in actor/A3 output, unbounded summary
growth, non-enum oracle retrieval, weakened/truncated A0, silent A3 protected
state loss, replay nondeterminism, unknown receipt fields, and constant action
probes. These are development qualification guards, not Stage A observations.

Event references fail closed before A3 compilation. Assertion dependencies and
supersession may target only earlier assertion events; refutations and commitment
preconditions may target only earlier assertions; commitment dependencies may
target only earlier commitments; an observed action effect must identify an
earlier dispatch. Unsupported source kinds with non-empty reference fields and
wrong target kinds raise `ContractViolation`, never a raw lookup error.

Repeated `ACTION_DISPATCHED` records may retain the same `action_ref`; `event_id`
remains the dispatch identity. Under this current Batch-2A contract, a later
effect with that `action_ref` binds to the most recent preceding dispatch, while
older unverified dispatch records remain visible. Batch-2B records this existing
behavior in a characterization test and does not change it.

### Batch-2B Stage-A preregistration candidate

Batch-2B adds the canonical candidate bytes at
`docs/pre_spec/R-STATE-CREDIT-1.STAGE-A.PREREG-CANDIDATE-2026-07-15.json` and a
candidate-only builder/validator in
`experiments/r_state_credit_1/prereg_candidate.py`. The candidate predeclares:

- exact A0/A1/A2/A3 arm roles, including A0 as the mandatory strong cheap
  baseline and the full-log stop rule;
- all seven scenario families, required perturbations, a 20--60 action failure
  delay inside a 23--72 step episode envelope, four decision checkpoints, 20
  disjoint held-out seeds per family, and one result-bearing pass only after a
  future exact lock;
- matched observable/representation/step/tool/wall-clock budgets and an
  API-only actor-binding contract that must be resolved at final freeze;
- one safety-weighted primary endpoint against A0, exact effect/sign/family and
  unsafe-replay gates, descriptive secondary metrics, no-imputation rules, and
  closed `MET / NOT_MET / INVALID` grammar;
- C7 abort authority, no score/threshold editing, no self-approval, no training,
  no Stage-B authority, and explicit no-rescue stop rules;
- exact source-file digests plus mandatory actor, corpus, scorer, reviewer and
  run-authorization bindings for any later freeze lock.

The validator accepts only canonical JSON bytes matching the generated protocol
and current source manifest. It rejects result fields, status upgrades, arm,
scenario, budget, seed, metric, missing-data, verdict, C7/authority and source
manifest drift. Its receipt is always `VALID_CANDIDATE_ONLY` with
`freeze_authority=false`, `run_authority=false`, and
`training_authority=false`.

The only command added by Batch-2B renders or validates candidate bytes:

```bash
PYTHONPATH=src python -m experiments.r_state_credit_1.prereg_candidate --check \
  docs/pre_spec/R-STATE-CREDIT-1.STAGE-A.PREREG-CANDIDATE-2026-07-15.json
```

It cannot freeze, execute arms, call a provider, score outcomes, adjudicate a
verdict, train a model, or create a result artifact. Independent review, exact
corpus/actor/scorer bindings, an exact-content lock, C7 owner and founder/CTO run
authorization remain absent and mandatory before any result-bearing execution.

## 4. Stage A to Stage B gate

Stage B may study learnable latent state, representation updates, or hierarchical
credit only if all of the following hold:

1. a separate Stage A preregistration and exact-content lock exist before any
   result-bearing run;
2. the mechanism and every baseline pass an independent implementation-faithfulness
   review;
3. one Stage A arm survives its frozen gate and does not merely beat a weak arm;
4. the survivor clears the full-log stop rule on disjoint held-out tasks/seeds;
5. oracle access, information volume, model compute, tool budget, and human
   intervention are accounted for explicitly;
6. the original Stage A verdict and all negative cases remain immutable;
7. Stage B receives its own Architecture-Theory Gate, design packet,
   preregistration, manifest, reviewer identity, and founder/CTO run decision.

Only the frozen Stage A survivor may enter Stage B. This implementation does not
select A3 and does not authorize Stage B code, training data, parameter updates,
result runs, or promotion.

## 5. Implemented state contracts

The local module is `src/aac/persistent_task_state.py`.

### 5.1 Closed records

- `EntityState`: stable identity, object version, monotonic revision, observed
  keys, aliases, evidence, and tombstone state.
- `Assertion`: entity/version binding, epistemic class, confidence, valid time,
  transaction time/version, provenance, evidence, dependencies, supersession,
  and explicit status.
- `CommitmentState`: immutable deliverable contract with status revision,
  assertion/commitment preconditions, postconditions, and evidence requirements.
- `DecisionRecord`: exact decision-time state digest, alternatives, selected
  action, relied-on assertions, predicted postconditions, and monotonic
  dispatch/receipt/effect state.
- `StatePatchCandidate`: typed transactional mutation with task identity, CAS
  base version/digest, transaction time, and append-only patch identity.
- `TaskStateSnapshot`: deterministic current projection plus the complete ordered
  patch-id and patch-digest chain.
- `TaskStateProjection`: bounded model-facing view tied to its source digest.

All records are frozen dataclasses with closed-field construction. Unknown fields,
untyped collection substitutions, invalid enum values, naive timestamps, invalid
digests, and illegal revisions fail closed.

### 5.2 Reducer invariants

`TaskStateReducer` enforces:

- compare-and-swap on both snapshot version and digest;
- deterministic ordering and SHA-256 canonical digests;
- no duplicate patch, entity, assertion, commitment, or decision identifiers
  within their applicable append-only/transaction boundary;
- entity revision by exactly one, preserved identity keys/aliases/evidence, and
  irreversible tombstoning;
- assertions bound to the current object version and patch transaction time;
- deterministic valid-time reads over the selected transaction snapshot using
  half-open intervals `[valid_from, valid_to)` and explicit timezone-aware input;
  valid-time reads never consult wall clock or rewrite historical status;
- contradictions represented as `CONFLICTED`, never latest-write-wins;
- explicit `SUPERSEDED`, `REFUTED`, and `STALE` states with transitive dependency
  invalidation;
- dependent commitments changed to `BLOCKED` when their support becomes invalid;
- decision rationale bound to the exact base snapshot and only its active
  assertions;
- decision revisions limited to monotonic execution-state facts;
- deterministic rehydration from the ordered patch chain;
- protected state retained during projection, with `STATE_OVERFLOW` instead of
  silently dropping active/conflicted/dependency-bearing state;
- recovery output limited to `RESUME`, `VERIFY_EFFECT`, or `ABSTAIN`; an
  ambiguous dispatched effect is never converted into replay authorization.

## 6. Non-duplication and authority boundaries

| Existing line | Boundary in this packet |
|---|---|
| Product task/event/runtime state | no imports, adapters, replacement, or runtime wiring |
| R-CSL-1 commitment ledger | `CommitmentState` is a research representation record, not execution or disposer authority |
| Stage 1 failure attribution | records dependency structure only; performs no causal or credit attribution |
| SPINE/LH recovery | emits no Product action and cannot bypass capability, approval, receipt, evidence, or C7 paths |
| CWM/world-model research | contains no causal discovery, latent dynamics, oracle, or world-model claim |
| B1 unified-model sandbox | contains no model, optimizer, dataset, gradient, adapter, or training path |

There is no cross-repository import and no framework or model receives final
execution, evaluation, promotion, or correction authority.

Repository placement follows `codebase_index.md`: `src/aac/` is Research Track,
while Product Track runtime lives under `packages/os_core/`, contracts under
`packages/contracts/`, and application entry points under `apps/`. The committed
module is imported only by its Research Track test; `apps/`, `packages/`, and
`domain_packs/` contain no import of `aac.persistent_task_state`. Path placement
and import absence do not authorize later Product promotion.

Transaction time and valid time remain separate. The selected
`TaskStateSnapshot` and its append-only patch/digest chain define the transaction
snapshot being read. `assertions_valid_at(..., valid_time=...)` filters only that
snapshot's currently `ACTIVE` or `CONFLICTED` assertions by explicit valid time.
Advancing wall clock alone cannot mutate an assertion to `STALE`; any historical
transaction-snapshot query or automatic temporal transition would require a new,
separately specified contract.

## 7. Verification boundary

The mechanism tests live in `tests/test_persistent_task_state.py`; the hermetic
arm and candidate guards live in `tests/test_r_state_credit_1_batch2a.py` and
`tests/test_r_state_credit_1_prereg_candidate.py`. They cover:

- closed/immutable schemas and unknown-field rejection;
- deterministic digest, CAS, duplicate-patch rejection, and rehydration equality;
- entity/version/time semantics;
- duplicate-entity rejection, half-open valid-time boundaries, overlapping versus
  non-overlapping conflict, supersession, refutation, tombstone, and dependency
  cascades;
- commitment contract immutability and blockage;
- safe projection and `STATE_OVERFLOW`;
- decision snapshot binding, monotonic execution revisions, and fail-closed
  interrupted-effect recovery.

Passing these tests is implementation evidence only. It is not a Stage A
experimental result. Before any result-bearing run, the experiment design, exact
metrics, thresholds, manifests, task instances, information accounting, reviewer
identity, and run authority must be frozen in a separate preregistration.

## 8. Current disposition

```text
Stage A typed-state mechanism: IMPLEMENTED_LOCAL_MECHANISM_ONLY
Batch-2A hermetic environment: IMPLEMENTED_LOCAL_QUALIFICATION_ONLY / NOT_EVIDENCE
Batch-2B prereg candidate: GENERATED_AND_MACHINE_VALIDATED_CANDIDATE_ONLY
Stage A comparison: NOT_PREREGISTERED / NOT_FROZEN / NOT_RUN
Stage A winner: NONE
Stage B: NO_STAGE_B_WINNER / NO_TRAINING / NO_RUN_AUTHORITY
Product integration: NONE
Research claim: NONE BEYOND LOCAL SOFTWARE INVARIANTS
```
