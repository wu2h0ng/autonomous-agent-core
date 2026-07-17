# R-NONORACLE-INTERVENTION-SHIFT-1 Design

> Status: `DESIGN_APPROVED / IMPLEMENTED / QUALIFICATION_ONLY / NOT_FROZEN / NOT_RUN`
> Track: `Research`
> Base: `c72375acb71c6a60cb0287cbd185ff07a196e0bd`

## Question

Can a mechanism that never receives a gold graph, ancestry oracle, target
shortlist, or scorer output turn anonymized observational/interventional rows
and authenticated intervention-target metadata into independently scoreable
directed ancestry hypotheses?

This slice does not test general causal discovery. It tests one narrow middle
link that prior routes failed to establish: data to explicit relation
hypotheses, before a separately custodied hidden scorer evaluates them.

## Chosen approach

Implement a deterministic intervention-stability mechanism. For every legal
`do(X)` condition and non-self target `T`, it compares the `T` distribution
against the within-batch observational control, estimates signed standardized
shift on two deterministic row partitions, and accepts `X ->* T` only when:

1. both partitions agree on direction;
2. both exceed a data-derived null threshold produced by deterministic label
   permutations; and
3. the pooled shift is finite and within the closed input contract.

The output is a ranked tuple of `DirectedAncestryHypothesis` records with
effect, stability and provenance digests. It contains no score or verdict.

## Rejected alternatives

- Rank-PC skeleton plus intervention orientation repeats the already-run Stage
  A probe and expands threshold/multiple-testing freedom before the narrow
  middle link is established.
- An anonymized LLM orientation organ adds provider and memorization confounds
  before a deterministic oracle-deleted mechanism exists.
- GSE42528 mediator/codec routes remain parked because an exact-map direct
  predictor is behaviorally identical and no independent structure truth
  exists.

## Components and data flow

1. `InterventionDataset` validates closed anonymous variable IDs, numeric rows,
   condition labels, intervention bindings and minimum control/intervention
   support. Missing or ambiguous bindings fail closed.
2. `InterventionStabilityDiscoverer` receives only that dataset and a frozen
   calibration contract. It cannot receive gold, scorer, expected edges or
   target lists.
3. Cheap baselines consume the identical public view and emit the identical
   hypothesis type:
   - exact-k observational absolute correlation with a frozen, variable-name-
     independent tie break;
   - fixed-threshold pooled mean shift without stability;
   - finite screen declaring every legal driver-target pair.
4. A qualification harness uses synthetic fixtures only. A future hidden
   scorer is a separate custody surface and is not invoked by this package.
5. A freeze-candidate manifest binds the complete executable package file set,
   calibration, baseline definitions and attack-test names. A sealed runner
   verifies externally supplied exact bindings, copies only those bytes, and
   runs them under `python -I -S` with a minimal environment. It grants no run
   authority.

## Decisive qualification case

Synthetic qualification must include a confounded/indirect-path environment
where observational correlation ranks a non-causal/reverse-associated pair and
a pooled mean-shift arm accepts an unstable batch artifact, while consistent
intervention partitions preserve the genuine ancestry relation and reject the
artifact. This proves the harness can distinguish the proposed mechanism from
both cheap baselines; it is not result evidence.

## Leakage and shortcut attacks

- The public API has no gold input. Exact external source binding rejects any
  changed or additional executable byte before the isolated runner imports it.
- The runner is not a general Python sandbox and does not claim that arbitrary
  approved malicious Python cannot perform I/O. Its narrower boundary is:
  reviewed exact source set, no unbound package file, isolated interpreter,
  minimal inherited environment and no injected project secrets.
- A bijective variable-ID rename produces an equivalently renamed output.
- Row order and within-condition order cannot change output.
- Removing, duplicating or contradicting intervention metadata fails closed.
- Public mechanism modules may not import or reference `GROUND_TRUTH`,
  `ancestors`, `sachs_task`, scorer, gold-graph files or protein names.
- The mechanism API has no gold/scorer/expected-edge parameter and rejects
  unknown serialized fields.
- Qualification asserts output changes when public interventional evidence
  changes, preventing a constant or finite-screen implementation from passing.
- Qualification disposition rejects any missing, extra or wrong hypothesis,
  non-exact-k comparator, or missing attack/calibration/binding gate.

## Freeze and claim boundary

This package may run unit and synthetic qualification tests. It must not score
real Sachs data, read the Sachs consensus graph, write a result artifact, or
claim discovery performance. Completion state remains
`IMPLEMENTED / QUALIFICATION_ONLY / NOT_FROZEN / NOT_RUN` until independent
review, exact-manifest acceptance, founder freeze and separate run authority.
