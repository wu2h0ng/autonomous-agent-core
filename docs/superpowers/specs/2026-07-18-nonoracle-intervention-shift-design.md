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
newer corpora because it provides useful crossed blocks for a cheap route kill
without creating a data-platform project: two donors mixed 1:1 before loading,
four physical GEM wells per condition, two selected sgRNAs per target, roughly
56,000 cells and 70 screen hits plus control guides. Donor is a biological
source block; GEM well is a technical replicate of the mixed culture, not an
independent biological replicate. The initial context is restimulated primary
human T cells only.

Primary sources:

- GEO: <https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE190604>
- Science paper: <https://doi.org/10.1126/science.abj4008>
- Zenodo analysis package, whose record is CC-BY-4.0:
  <https://zenodo.org/records/5784651>

The Zenodo license does not assign the same license to the GEO matrix. The
curator must record the GEO usage basis separately before acquisition.

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
guide calls plus the Zenodo archive with locally computed SHA-256 digests. It
must also bind the barcode-suffix-to-well/GSM map, guide-to-target library map,
Souporcell calls, cross-well donor-label harmonization provenance and the
stimulated-condition selector. Donor labels are derived analysis outputs, not
raw GEO metadata. The upstream Zenodo MD5 is transport context only. No hidden
effect, paper DE, cluster, pathway or activation label may influence eligibility.

The route is immediately `PARK` if the join is ambiguous; fewer than 40 targets
have two guides and support on both GUIDE sides plus diagnostic subgroups; any aggregate
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
exclude donor doublets and unassigned cells only if the bound author analysis
object/script proves that exact rule
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

Use one decisive holdout and two non-decisive stress diagnostics:

| Fold | Public builder rows | Hidden scorer rows | Independence |
|---|---|---|---|
| `GUIDE` decisive | one scorer-HMAC-selected target sgRNA plus disjoint HMAC-selected NTC guides | the other target sgRNA plus disjoint NTC guides | intervention implementation |
| `DONOR_DIAGNOSTIC` | no additional builder input | scorer stratifies locked GUIDE predictions and hidden-guide outcomes by donor | scorer-only veto diagnostic |
| `WELL_DIAGNOSTIC` | no additional builder input | scorer stratifies locked GUIDE predictions and hidden-guide outcomes by two pre-frozen lane-balanced well groups | scorer-only veto diagnostic |

Guide selection must use a scorer-custodied HMAC over target-guide identity,
never paper `_1/_2` ordering. A separate precommitted HMAC partitions NTC guides;
no NTC guide, cell or barcode may appear on both GUIDE sides. Aggregation preserves
the natural `donor × well × guide` blocks; it must not manufacture eight rows to
fit the current 20,000-combination ceiling. If paired treated/control blocks can
be constructed, the null is a predeclared within-block sign swap (for eight
pairs, `2^8`), not an unrestricted `C(16,8)` label permutation. Otherwise the
metadata gate returns `PARK_BLOCK_CONSTRUCTION`. The current unblocked mechanism
is not compatible with this amendment until it consumes an explicit block
contract. DONOR and WELL outputs are descriptive direction/degeneration checks,
not independent confirmation or formal non-inferiority folds. The builder sees
only the GUIDE-public rows. DONOR/WELL diagnostics run inside the scorer after
all GUIDE arm digests are locked; they never expose additional rows or create a
second builder-visible fold.

For each GUIDE side, all HMAC-assigned NTC-guide raw counts are summed within
each `donor × well` block to create exactly one control pseudobulk. Each target
guide pseudobulk is paired only with that same block's control. A precommitted
secondary HMAC partitions the public-side NTC guides into A/B groups; the
within-`donor × well` A-minus-B contrasts are the only public NTC
pseudo-contrasts used for scaling. Empty A/B groups, a missing paired control or
an ambiguous natural block is `PARK_BLOCK_CONSTRUCTION`. The design constant is
`s_floor = 0.25`; it is not estimated after public or hidden inspection.

### Hidden outcome and proper score

For each legal `(fold, X, T)`, `X != T`, the curator freezes a public-only scale
`s[T,fold]` from public NTC block pseudo-contrasts. The independent scorer then
computes the held-out shift in the same unit:

```text
s[T,fold] = max(s_floor, 1.4826 * MAD(public NTC block pseudo-contrasts for T))
Y[X,T,fold] =
  (mean(hidden treated logCPM_T) - mean(hidden NTC logCPM_T)) / s[T,fold]
```

Every arm emits fold-specific `mu[X,T,fold]` in that same public-scaled unit; a
missing hypothesis means `mu=0`. The public compiler freezes `s_floor`, zero or
near-zero scale handling, missing/finite rules and the exact mapping from each
arm's public estimate to `mu`. Hidden SD is never used to scale either side.

```text
sigma[T,fold] = 1.0
```

This is a fixed-variance Gaussian location score on public-standardized units;
Normal negative log likelihood is primary and Normal CRPS secondary. AP, F1 and
sign agreement are diagnostics only. Pairing is on identical GUIDE `(X,T)`
units. `T` is the support-conditioned set of eligible guide-target genes, not all
expressed genes. Every arm must emit a finite `mu` for every legal `(X,T)`; a
missing hypothesis maps to zero and no pair is dropped. For each arm, loss is
averaged equally over all eligible `T` within each source `X`, then averaged
equally across `X`. The decisive output is this finite-panel macro paired loss
delta versus every mandatory competitive arm, with shared NTC and source/target
dependence retained in the reported block table. No cell-level bootstrap, post-hoc choice between bootstrap
and sign-flip, donor/well independence claim or formal p-value is permitted in
the first route kill. A later inferential freeze requires a separately reviewed
simultaneous source×target/shared-block procedure and a pre-data sensitivity
analysis.

### Strong cheap baselines and route killers

Every arm receives the same public rows, variable universe, budget and scale:

1. `ZERO_EFFECT`;
2. `RAW_POOLED_ALL_PAIRS` without stability filtering;
3. `BLOCK_MEDIAN_SHIFT`;
4. mandatory donor/well-blocked `edgeR` quasi-likelihood on raw integer
   pseudobulk counts and library sizes, with a frozen mapping to the shared
   public scale;
5. rank-one `SOURCE_STRENGTH_X_TARGET_SUSCEPTIBILITY`;
6. the existing matched-k observational correlation and finite-screen sanity
   baselines.

Mandatory competitive route killers are `ZERO_EFFECT`,
`RAW_POOLED_ALL_PAIRS`, `BLOCK_MEDIAN_SHIFT`, blocked `edgeR` QL,
`SOURCE_STRENGTH_X_TARGET_SUSCEPTIBILITY` and the matched-k observational
correlation arm. `FINITE_SCREEN_ALL_LEGAL_PAIRS` is a serialization/plumbing
sanity arm only.

If any mandatory competitive arm matches or beats the mechanism on primary
macro-averaged NLL, the route is `PARK`; ties are baseline wins. Threshold,
eligible panel, folds and scorer may not be changed to rescue it. Primary NLL
precedence is absolute. Only if the mechanism beats every competitive arm on
NLL is CRPS evaluated as an additional AND gate: improvement over the best
competitive arm must be at least 2% using denominator
`max(abs(champion_crps), 1e-6)`. The 2% value is a founder route-ROI margin,
requires a public-only sensitivity calculation before freeze and is not a
statistical-significance claim.

For veto diagnostics, the scorer macro-averages the same GUIDE hidden loss delta
within each donor and within each of two pre-frozen lane-balanced well groups.
A single subgroup reversal is reported only. Both donor macro-deltas less than
or equal to zero, or both well-group macro-deltas less than or equal to zero,
triggers scientific `PARK`. Finite-screen remains a plumbing sanity arm and
cannot be a champion. These are design gates only; this amendment authorizes no
result run.

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

### Instrument and disposition boundary

CRISPRa guides are imperfect instruments: activation strength, noncompliance and
off-target effects remain possible. Cross-guide agreement reduces but does not
eliminate exclusion violations. The permitted characterization label is
`guide-target-anchored held-out expression-shift transport`; an `X ->* T`
ancestry claim would additionally require frozen source-induction fidelity,
consistency and exclusion assumptions that this package does not establish.

Metadata join/licensing/support failure, inability to construct the blocked
GUIDE split, a strong-baseline win, failure to meet the predeclared practical
margin or diagnostic reversal is `PARK`. Hidden overlap/exposure, identity or
digest mismatch, whole-data fitting, post-run gate changes, undefined-statistic
repair after opening, scorer import of mechanism code or role non-independence is
`INVALID`. Low support or zero public scale found by the pre-run qualification
gate makes the target ineligible and may trigger `PARK`; inventing a rule for it
after freeze invalidates the whole run.
