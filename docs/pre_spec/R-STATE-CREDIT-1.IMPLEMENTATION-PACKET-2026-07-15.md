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
- no duplicate patch or append-only assertion identifiers;
- entity revision by exactly one, preserved identity keys/aliases/evidence, and
  irreversible tombstoning;
- assertions bound to the current object version and patch transaction time;
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

## 7. Verification boundary

The targeted tests live in `tests/test_persistent_task_state.py` and must cover:

- closed/immutable schemas and unknown-field rejection;
- deterministic digest, CAS, duplicate-patch rejection, and rehydration equality;
- entity/version/time semantics;
- conflict, supersession, refutation, tombstone, and dependency cascades;
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
Stage A comparison: NOT_PREREGISTERED / NOT_FROZEN / NOT_RUN
Stage A winner: NONE
Stage B: NO_STAGE_B_WINNER / NO_TRAINING / NO_RUN_AUTHORITY
Product integration: NONE
Research claim: NONE BEYOND LOCAL SOFTWARE INVARIANTS
```
