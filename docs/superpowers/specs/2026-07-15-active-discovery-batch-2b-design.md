# Active Discovery Batch-2B Stage-A Qualification Design

> Status: `DESIGN_APPROVED / FREEZE_CANDIDATE_ONLY / NOT_FROZEN / NOT_RUN / NOT_EVIDENCE`
> Date: 2026-07-15
> Approved mechanism base: `fa9314ea8cd84c1ea33615d4382c5c5da7b74651`
> Scope: R-ACTIVE-DISCOVERY-1 Batch-2B only

## 1. Decision

Batch-2B will create a checked-in Stage-A **instrument-qualification**
preregistration candidate and a fail-closed validator. It will not create a
claim-ready scientific preregistration.

This boundary is load-bearing. At the approved base, F1-F4 `hidden_score`
implementations return the constant value zero, and changing a family seed only
changes opaque vocabulary rather than hidden semantics. Treating repeated seeds
as independent scientific samples or freezing a VOI-advantage threshold now
would create a mechanical or pseudoreplicated result. Batch-2B therefore permits
only these terminal verdicts:

- `QUALIFIED_FOR_NEXT_SCORING_SPEC`
- `REVISE`
- `INVALID_*`
- `STOPPED_NO_VERDICT`

It explicitly forbids `PASS`, `MET`, `NOT_MET`, `NULL`, `VOI_ADVANTAGE`, a
three-arm scientific ranking, or any autonomy/general-discovery claim.

## 2. Considered approaches

### A. Qualification candidate — selected

Freeze the experiment identity, exact mechanism bytes, family/split allocation,
matched budgets, referee seal contract, invalidation rules, missing-data policy,
C7 stop behavior and qualification verdict grammar. A later independently
reviewed batch must add non-trivial hidden scoring before a claim-ready
preregistration can exist.

### B. Freeze constant-zero scientific scoring — rejected

This would be executable but scientifically empty. It would consume a formal run
to obtain a mechanically predetermined tie or null and would invite false sample
size from label-only seed changes.

### C. Add hidden scoring and preregistration together — rejected

This would couple the evaluator, thresholds and preregistration under one writer
and exceed the bounded Batch-2B cast. Scoring needs its own exact-content review
before it can enter a result-bearing specification.

## 3. Artifacts and authority

Create:

- `research_tools/active_discovery/stage_a_prereg.py`: deterministic candidate
  builder, closed validator and read-only loader;
- `research_tools/active_discovery/stage_a_prereg_candidate.json`: materialized
  candidate produced by the same deterministic builder;
- `tests/research_tools/test_active_discovery_stage_a_prereg.py`: contract,
  tamper, source-drift and boundary tests;
- this design and the matching implementation plan.

Modify only:

- `tests/research_tools/test_active_discovery_unified_adapter.py` to extend the
  existing actor-surface leakage regression to F1 vocabulary.

The validator has `VALIDATION_ONLY` authority. It cannot write a freeze lock,
invoke a runner, execute an arm, read a result, select a verdict for observed
data, or authorize a provider/model/training call.

## 4. Candidate identity and state

The top-level closed object binds:

- schema `active-discovery-stage-a-prereg-candidate/v1`;
- experiment `R-ACTIVE-DISCOVERY-1-STAGE-A`;
- mode `NOT_EVIDENCE`;
- candidate state `FREEZE_READY_CANDIDATE`;
- freeze state `NOT_FROZEN`;
- run state `NOT_RUN`;
- evidence state `NOT_EVIDENCE`;
- authority state `VALIDATION_ONLY`;
- approved mechanism base
  `fa9314ea8cd84c1ea33615d4382c5c5da7b74651`;
- canonical source-manifest, family-matrix, hidden-truth-seal and candidate
  digests.

Unknown, missing or differently typed fields fail validation. The candidate
digest is domain-separated SHA-256 over canonical JSON excluding only the
`candidate_digest` field.

## 5. Family and held-out split

The allocation is exact and cannot be reassigned after inspection:

| Family | Role | Qualification seed | Evaluation seed |
|---|---|---:|---:|
| F1 | `QUALIFICATION_FAMILY` | 101 | 1009 |
| F2 | `QUALIFICATION_FAMILY` | 103 | 1013 |
| F3 | `QUALIFICATION_FAMILY` | 107 | 1019 |
| F4 | `HELD_OUT_FAMILY` | none | 1021 |

Every non-null manifest is the complete closed `FamilyManifest` mapping plus its
derived `manifest_digest`. The validator rebuilds it through
`UnifiedFamilyAdapter`, verifies exact equality and rejects seed reuse,
family-code drift, role drift, hidden-configuration digest drift or post-hoc
split reassignment.

F4 is an allocation holdout only. The project must not claim that F4 was unseen
by the mechanism author, because its implementation already exists at the
approved base.

## 6. Matched arm contract

The only arms are, in this order:

1. `SYSTEMATIC`
2. `RANDOM`
3. `VOI`

Each arm binds:

- exact budget `4` unit-cost probes;
- the same evaluation-family matrix digest;
- the same family manifest and candidate catalogue per cell;
- fresh adapter construction;
- the same seal and stop rules.

The sole random ordering seed is `1701`. No arm-specific budget, family subset,
hidden transition, hidden score, oracle label or post-seal feedback may enter
selection. Stage-A does not compare the arms' scientific quality.

## 7. Hidden truth and leakage

The candidate contains only a commitment over evaluation manifest digests and
hidden-configuration digests. Raw hidden semantics are not part of the candidate
or actor surface. Access policy is exactly
`REFEREE_ONLY_AFTER_TRANSCRIPT_SEAL`.

The following are invalid before seal or on the actor surface:

- raw hidden configuration or semantic switches;
- source/package/version/family identity labels;
- hidden tests, referee score or oracle output;
- manifest, seal payload or hidden-configuration field names;
- family implementation class names;
- F1 semantic vocabulary: `source_precedence`, `repeat_mode`, `unknown_mode`,
  `empty_is_missing`, `atomic_on_error`, `opaquecli`;
- corresponding F2-F4 semantic vocabulary already covered by Batch-2A tests.

Any detected leakage yields `INVALID_LEAKAGE`; pre-seal hidden-truth access yields
`INVALID_HIDDEN_TRUTH_ACCESS`. Neither is downgraded to missing data or `REVISE`.

## 8. Qualification metrics and missing data

This candidate freezes only integrity metrics:

- expected evaluation cells: `4 families × 3 arms = 12`;
- complete sealed receipt count: exactly `12`;
- exact-budget receipt count: exactly `12`;
- pre-seal hidden-truth access count: exactly `0`;
- leakage violation count: exactly `0`;
- C7 post-stop adapter access count: exactly `0`.

There is no imputation, arm dropping, family dropping, duplicate-cell collapse,
metric substitution or post-hoc threshold change. Missing, duplicate or extra
cells yield `INVALID_MISSING_DATA`, except that a clean C7 halt yields
`STOPPED_NO_VERDICT` and no partial verdict.

No metric in this batch measures VOI superiority, contract accuracy, calibration
or evaluator generalization. A later scoring spec must add those quantities and
undergo independent review before freeze.

## 9. C7, stop and verdict precedence

The halt authority is checked before any dynamic adapter state read or execute
call. Once halted, no new adapter, state, probe, seal or score access is allowed.

Verdict precedence is fail-closed:

1. any leakage, hidden-truth, manifest/split, source, budget or post-stop access
   violation that occurred before or during the halt boundary → the matching
   `INVALID_*`;
2. clean external halt with no prior integrity violation, where missing cells
   are caused only by that halt → `STOPPED_NO_VERDICT`;
3. without a clean-halt exception, any missing, duplicate or extra cell →
   `INVALID_MISSING_DATA`;
4. complete but non-qualifying integrity metrics → `REVISE`;
5. every frozen qualification condition satisfied →
   `QUALIFIED_FOR_NEXT_SCORING_SPEC`.

The final status authorizes only design of a separately reviewed scoring spec.
It does not authorize freeze, run, result, model/provider access or training.

## 10. Source manifest

The source manifest contains sorted repository-relative paths and raw-byte
SHA-256 digests for every result-affecting Stage-A mechanism plus the validator:

- `canonical.py`, `contracts.py`, `budget.py`, `selector.py`, `catalogue.py`,
  `referee.py`, `arm_runner.py`;
- `families/manifest.py`, `families/unified.py`, and all four opaque family
  implementations;
- `stage_a_prereg.py`.

The materialized JSON file is excluded to avoid self-hash recursion; its entire
semantic content is bound by `candidate_digest`. A later real freeze must bind
the raw candidate bytes, candidate commit, independent review identities and
runner-owned lock separately.

## 11. Validation and non-actions

Tests must prove:

- checked-in candidate equals the deterministic builder output;
- source, manifest, family role/seed, matrix, budget, seal, metric, missing-data,
  leakage, C7 and verdict tampering all fail;
- JSON key order does not change canonical digest;
- F1 actor output excludes F1 semantic vocabulary;
- a clean early halt returns `STOPPED_NO_VERDICT`, while a halt preceded by an
  integrity violation returns the matching `INVALID_*`;
- no production path writes a freeze or invokes runner/model/provider code.

F4 self-loop behavior is intentionally unchanged. Its present public contract is
not precise enough to justify a semantic tightening in this batch.
