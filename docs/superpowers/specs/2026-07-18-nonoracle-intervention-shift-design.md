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
- Even when all local conditions are met, the only positive disposition is
  `LOCAL_CONDITIONS_MET_NOT_FREEZE_AUTHORITY`; it always carries
  `freeze_authorized=false` and `run_authorized=false`. Caller-supplied local
  gate assessments cannot mint review, freeze or run authority.

## Freeze and claim boundary

This package may run unit and synthetic qualification tests. It must not score
real Sachs data, read the Sachs consensus graph, write a result artifact, or
claim discovery performance. Completion state remains
`IMPLEMENTED / QUALIFICATION_ONLY / NOT_FROZEN / NOT_RUN` until independent
review, exact-manifest acceptance, founder freeze and separate run authority.

## 2026-07-18 real-data qualification amendment

> Amendment status: `CHARACTERIZATION_ONLY / DATA_NOT_ACQUIRED / NOT_FROZEN / NOT_RUN`
> Package id: `R-NONORACLE-PERTURB-KILL-1`

### Selected source and claim ceiling

The first real-data qualification source is `GSE190604`, the Schmidt–Steinhart
primary human T-cell CRISPRa Perturb-seq dataset. It is preferred over larger
newer corpora because it provides the crossed replication needed for a cheap
route kill without creating a data-platform project: two donors, four physical
GEM wells per condition, two sgRNAs per target, roughly 56,000 cells and about
70 hit/control targets. The initial context is restimulated primary human
T cells only.

Primary sources:

- GEO: <https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE190604>
- Science paper: <https://doi.org/10.1126/science.abj4008>
- Zenodo analysis package, CC-BY-4.0:
  <https://zenodo.org/records/5784651>

Any positive result is limited to held-out intervention-shift transport inside
the author-selected CRISPRa panel and stimulated T-cell context. It does not
establish direct edges, a complete causal graph, unseen-intervention zero-shot
discovery, non-oracle intervention selection, cross-domain generality, Product
capability or `Autonomy(S,E,O,V,T)`.

### First gate: metadata-only feasibility

Before scorer or mechanism work, a curator must prove that public source bytes
support a unique join for:

```text
cell barcode × donor × physical well × guide × guide target × condition
```

The source manifest must bind the GEO matrix, barcodes, features and aggregated
guide calls plus the Zenodo archive with locally computed SHA-256 digests. The
upstream Zenodo MD5 is transport context only. No hidden effect, paper DE,
cluster, pathway or activation label may influence eligibility.

The route is immediately `PARK` if the join is ambiguous; fewer than 40 targets
have two guides and support on both sides of all required folds; any aggregate
has fewer than 10 treated cells; any NTC aggregate has fewer than 25 cells; the
public/hidden split requires a whole-data fitted transform; or source licensing
or checksums are not reproducible.

### Public compiler boundary

Use raw UMI counts only. Apply the paper-compatible fixed QC:

```text
exactly one guide
guide UMI >= 5
mitochondrial fraction < 25%
400 < detected features < 6000
exclude donor doublets and unassigned cells
```

Pseudobulk within `donor × well × guide`, then apply row-local `log1p(CPM)`.
Cells are never treated as independent observations. Builder-visible IDs are
bijective opaque IDs; the authenticated guide-to-target binding remains opaque.
Gene symbols, guide rank, UMAP, clusters, activation scores, paper DE/FC/p-values,
SCT slots, cytokine-screen ranking, pathway annotations, hidden split labels and
scorer outputs are forbidden builder inputs.

### Qualification folds

A true perturbation-level holdout is not compatible with the current mechanism:
`discover()` must observe `do(X)` rows before it can emit `X ->* T`. Hiding all
rows for `X` and then claiming unseen-perturbation discovery is
`PARK_DESIGN_MISMATCH`.

Use three complementary folds instead:

| Fold | Public builder rows | Hidden scorer rows | Independence |
|---|---|---|---|
| `GUIDE` primary | one scorer-HMAC-selected sgRNA, two donors × four wells | the other sgRNA | intervention implementation |
| `DONOR` | one scorer-HMAC-selected donor, two guides × four wells | the other donor | biological donor |
| `WELL` | two lane-balanced wells, two donors × two guides | the other two wells | physical GEM well |

Guide selection must use a scorer-custodied HMAC over the guide identity, never
paper `_1/_2` ordering. If lane identity is unavailable, the third fold is named
`WELL_HOLDOUT`, not sequencing-lane holdout. Each side must compile exactly
eight treated and eight NTC control block rows, giving an exact permutation
space of `C(16,8)=12,870`, below the existing 20,000-combination ceiling.

### Hidden outcome and proper score

For each legal `(fold, X, T)`, `X != T`, the independent scorer computes a
standardized held-out shift:

```text
Y[X,T,fold] =
  (mean(hidden treated logCPM_T) - mean(hidden NTC logCPM_T))
  / pooled hidden block SD
```

Every arm emits `mu[X,T]`; a missing hypothesis means `mu=0`. A target-specific
prediction scale is frozen from public NTC pseudo-contrasts and shared by every
arm:

```text
sigma[T] = max(0.25, 1.4826 * MAD(public NTC pseudo-contrasts for T))
```

Primary score is Normal negative log likelihood. Normal CRPS is secondary.
AP, F1 and sign agreement are diagnostics only. Pairing is on identical
`(fold,X,T)` units; inference first averages targets within each source
intervention and then uses source-cluster paired bootstrap/sign-flip with a
manifest-derived seed. Cell-level bootstrap is prohibited.

### Strong cheap baselines and route killers

Every arm receives the same public rows, variable universe, budget and scale:

1. `ZERO_EFFECT`;
2. `RAW_POOLED_ALL_PAIRS` without stability filtering;
3. `BLOCK_MEDIAN_SHIFT`;
4. mature donor/well-blocked `limma-voom` empirical Bayes or `edgeR` QL;
5. rank-one `SOURCE_STRENGTH_X_TARGET_SUSCEPTIBILITY`;
6. the existing matched-k observational correlation and finite-screen sanity
   baselines.

If raw pooled shift or the mature blocked empirical-Bayes baseline matches or
beats the mechanism, the route is `PARK`; threshold, variable universe, folds
and scorer may not be changed to rescue it. The freeze package, if ever
authorized, must also require the primary GUIDE fold to beat every strong
baseline under Holm-corrected source-cluster inference, at least 2% CRPS
improvement over the champion, and no greater than 2% material degradation on
DONOR or WELL. These are design gates only; this amendment authorizes no result
run.

### Custody topology

```text
curator -> public opaque manifest + sealed hidden manifest
builder -> arm outputs, exits before hidden mount exists
scorer -> separate identity, hidden rows after all arm digests are locked
adjudicator -> verifies source/split/arm/scorer digests and applies precedence
```

`builder_id != scorer_id != adjudicator_id`. The scorer cannot import mechanism
code. Identity mismatch, hidden-byte exposure before arm lock, ID-only shortcut
predictive value, non-bijective renaming, row-order dependence or caller-writable
eligibility makes the package `INVALID`, not a weak negative result.
