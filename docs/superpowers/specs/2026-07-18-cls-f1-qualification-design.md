# CLS-F1 A→B→A Continual-Retention Qualification Design

> Status: `QUALIFICATION_CANDIDATE / NOT_FROZEN / NOT_RUN`
> Track: `R`
> Claim class: qualification instrument only
> Base: `8c090f1604b83a6d10c3a1cbe6f557cfe1553e6e`

## 1. Foundational question and claim ceiling

The instrument asks one narrow question from F1/TC1 in
`docs/research/neuroscience-grounding-cognition-memory-2026-06-23.md`:

> Does a dual-store fast/retained memory candidate provide a simultaneous
> adaptation-and-return-retention advantage over a budget-matched cheap
> single-store replay plus functional-stability baseline in a non-trivial
> A→B→A action setting?

It may qualify or kill the CLS strict-dominance route inside the frozen
operating envelope. It cannot establish autonomy, general intelligence,
cross-domain transfer, product value, or superiority outside this benchmark.

The existing two-action W1/W2 characterization is not evidence for this claim.
`ReactiveWSLSArm` and `ScheduledKnownArm` can saturate that toy, and the latter
has schedule oracle access. This design does not modify that harness or reuse
its result semantics.

## 2. Rejected approaches

- **Extend the two-action W1/W2 harness:** rejected because W1/W2 authority and
  state-consumption questions would be confounded with continual retention,
  while the current task is already cheap-baseline saturated.
- **Small neural classifier with gradient EWC:** parked. It is more literal but
  imports training/dependency and classification confounds without improving
  the Agent OS action, correction, or cost question.
- **Selected:** a standalone, stdlib-only contextual action instrument with
  explicit information-access contracts, cost accounting, correction, and an
  oracle ceiling isolated from online non-oracle arms.

## 3. Environment

### 3.1 Hidden evaluator state

Each episode contains:

- eight latent task contexts;
- four authorized actions;
- three phases, exact `A→B→A`, with seed-randomized phase lengths;
- a pre-generated context schedule with seed-randomized per-context occurrence
  counts, independent of every arm;
- delayed stochastic action feedback generated from evaluator-owned reward
  tables and common random numbers;
- exactly four changed contexts in B, selected before any arm runs; and
- four unchanged contexts used to measure negative transfer.

In A, each latent context has one optimal action. In B, the optimal actions of
the four changed contexts are deranged; unchanged contexts retain their A
mapping. The final A phase restores the exact original mapping. Correct and
incorrect actions use fixed reward probabilities separated enough for learning
but below deterministic saturation. Phase lengths, delay distribution, noise
probabilities, changed-context selection, and context schedule are freeze-bound
inputs, not tuned per arm.

### 3.2 Arm-visible contract

An online non-oracle arm receives only:

- a raw feature tuple;
- opaque currently authorized action tokens;
- delayed `(chosen_action, reward, event_digest)` feedback; and
- a typed correction event naming an invalidated feedback digest.

It never receives seed, turn, phase, switch schedule, latent context ID,
changed/unchanged status, optimal action, or evaluator metrics.

There is no explicit context identifier or fixed per-context phase counter. For every seed, the evaluator applies a
hidden bijection over feature dimensions and categorical value names. Action
tokens are also renamed by a hidden bijection. Isomorphic episodes under those
bijections must yield mapped-equivalent candidate actions and identical mapped
metrics. A failed equivariance test is oracle/table leakage and invalidates the
candidate.

### 3.3 Correction probe

At a freeze-bound step, the public stream includes one evaluator-generated,
plausible but incorrect delayed feedback event. A later typed correction
invalidates its digest permanently. Arms must
remove the invalidated event's influence using their own checkpoint/event
discipline. The correction carries no phase or optimal-action information.

## 4. Arms

All non-oracle adaptive arms receive identical observations, feedback,
corrections, action sets, total update budget, and total replay budget.

1. **Dual-store candidate**
   - fast recent action-value store;
   - slow versioned retained-prototype store;
   - prediction-error evidence may snapshot/reset fast state and retrieve a
     retained prototype;
   - no phase/task label, seed, schedule, or oracle metric;
   - every write, prototype copy, replay, comparison, and retrieval is charged.

2. **Single-store replay + functional stability** — strongest cheap baseline
   - one current action-value state per raw feature context;
   - bounded reservoir replay;
   - a functional EWC-equivalent penalty limiting changes to previously
     important action values without gradients;
   - the stability strength and detector parameters are selected only on the
     independent qualification seeds and frozen before result seeds;
   - receives exactly the same aggregate update/replay budget as the candidate.

3. **Reset-on-change baseline**
   - non-oracle context-local prediction-error detector;
   - resets affected current state and relearns; no retained prototype.

4. **Recency baseline**
   - bounded sliding-window action values with the same online feedback.

5. **Static baseline**
   - learns in initial A, then stops updating.

6. **Oracle context/phase ceiling**
   - evaluator-only;
   - receives latent context and phase and selects the evaluator-optimal action;
   - never participates in a non-oracle win or baseline comparison.

The existing WSLS policy may be included only as a triviality diagnostic. It
cannot substitute for the strongest single-store baseline.

## 5. Metrics and cost

Metrics are computed by the hidden scorer from sealed trajectories:

- **B adaptation speed:** changed-context exposures after A→B until the frozen
  rolling regret threshold is met for every changed context;
- **return-to-A retention:** reward/accuracy on the first frozen number of
  visits to each changed context after B→A, plus delta from the initial-A tail;
- **negative transfer:** B-phase degradation on unchanged contexts relative to
  their initial-A tail;
- **correction safety:** invalidated-event influence after correction,
  rollback latency, and post-correction unsafe/wrong-action count;
- **quality:** per-phase regret area and full-episode reward;
- **cost:** action-value updates, replay samples, detector comparisons,
  prototype copies/retrievals, stored event count, and canonical serialized
  state bytes.

No metric denominator may shrink after a halt or failure. Missing coverage is
scored as failure, not omitted.

## 6. Qualification, held-out custody, and budgets

- Mechanism parameters may be selected only on a declared qualification seed
  set.
- Result seeds are disjoint and externally custody-bound; this package does not
  contain or execute them.
- The same arm-independent episode corpus and counterfactual noise is used for
  every arm on a seed.
- The single-store and dual-store arms receive the same total environment
  steps, update operations, and replay operations. Unused budget is recorded,
  not reassigned after results are known.
- Parameter search counts and qualification seed exposures are reported as
  cost. The candidate cannot receive more search trials than the strongest
  baseline.
- This implementation ends at `QUALIFICATION_CANDIDATE / NOT_RUN`. Unit and contract
  tests are allowed; no multi-seed characterization or result-bearing run is.

## 7. Frozen disposition logic

These rules are conjunctive and evaluated against the strongest non-oracle
cheap baseline per seed before aggregation:

- **K1 — TC1 kill:** if the strongest cheap single-store is non-inferior on B
  adaptation speed (`≤ candidate + 1 context cycle`, capped at `10%` of the B
  horizon) and return-to-A retention differs by at most `0.03`, kill CLS strict
  dominance and classify the dual-store split as overhead.
- **K2 — no adoption:** if the candidate fails to improve either B adaptation
  speed or return retention, or is worse on negative transfer, correction
  latency, or post-correction unsafe actions, disposition is `NO_ADOPT`.
- **K3 — overhead:** if candidate state bytes or charged update/replay work
  exceeds `2×` the strongest baseline without at least `0.05` return-retention
  gain, disposition is `OVERHEAD`.
- **K4 — invalid:** any phase/task/oracle access, feature/action renaming
  non-equivariance, result-seed parameter tuning, budget mismatch, or continued
  consumption of an invalidated event makes the comparison `INVALID`.
- **K5 — trivial environment:** if a recency/WSLS cheap arm reaches at least
  `0.95` on the key quality/retention measures or the oracle ceiling gap is at
  most `0.03`, the environment is `TRIVIAL_INVALID` for the CLS claim.

A surviving candidate supports only this narrow statement: within the frozen
envelope, dual-store adaptation was simultaneously faster and more retentive,
was safety-non-inferior, and stayed inside the frozen cost bound. It is not a
general architecture adoption decision.

## 8. Implementation and tests

The package is isolated under `experiments/continual_retention_f1/` and exposes:

- closed observation, feedback, correction, arm-access, budget, trajectory,
  metric, evaluator-owned operation ledger, and disposition contracts;
- a seeded evaluator fixture that owns latent phase/context/reward truth;
- six arms with a shared online protocol;
- a run-neutral harness that can build and validate episodes but has no result
  authority;
- a hidden scorer and mechanical K1–K5 adjudicator; and
- an exact-content freeze-candidate manifest/preregistration candidate.

Red tests must establish at minimum:

1. observations exclude context/phase/schedule/seed/turn;
2. feature and action bijections preserve mapped behavior;
3. changed and unchanged contexts exist in every valid episode;
4. delayed feedback and correction never expose hidden state;
5. invalidated events stop influencing every adaptive arm;
6. candidate and strongest baseline budgets are exactly equal;
7. baseline stability parameters cannot be changed by result seeds;
8. oracle ceiling cannot instantiate through the non-oracle arm factory;
9. missing coverage cannot improve metrics;
10. each K1–K5 path is mechanically reachable with synthetic metric fixtures;
11. static/reset/recency/replay and dual-store are behaviorally distinct; and
12. no API in this package can mint freeze or result-run authority.

## 9. Stop conditions

Stop without a result run if the instrument cannot simultaneously enforce
non-oracle information access, permutation equivariance, equal adaptive budget,
correction invalidation, and scorer-owned metrics. Do not weaken those
conditions to preserve the candidate.
