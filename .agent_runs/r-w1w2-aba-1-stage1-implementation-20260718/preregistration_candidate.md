# R-W1W2-ABA-1 Stage 1 Preregistration Candidate

> State: `DRAFT_PUBLIC_PREREG_TEMPLATE / PREREG_REVISE / NOT_IMPLEMENTATION_READY / NOT_FROZEN / NOT_RUN`
> This artifact is not a freeze receipt or run authorization.

## 1. Exact design binding

- Package: `R-W1W2-ABA-1-STAGE1`
- Canonical Agent OS base: `6c94bd8c6f27da6d327a6841fd5c434e8e555206`
- Approved design source: `76c92c531d2f00fe2ddca754495f14079fedebf8`
- Design specification SHA-256: `3a534f6919fdc8c6936e49d2de3485f0619d200717ffad9a5ceb4ccb2be92904`
- Research basis SHA-256: `825a1969a541af71738c2692f8606d1a208105e013184828b0b6972b74978e1e`
- Approval receipt: `.agent_runs/r-w1w2-aba-1-design-20260718/messages.jsonl`, final `APPROVE_ABA_DESIGN_CANDIDATE`
- Receipt precedence: the final exact-byte approval supersedes stale internal workflow labels in `research.md`/`spec.md`; it does not alter `PREREG_REVISE / NOT_IMPLEMENTATION_READY / NOT_FROZEN / NOT_RUN`.
- Claim class: `R`, prospective route-kill only
- Claim envelope: locally replayable, reversible software version/interface/policy A→B→A shifts represented by a future accepted sampling frame

## 2. Foundational question and null

Question: Does bounded typed W1 state plus candidate W2 in-envelope strategy selection earn incremental value beyond W1-only, version-keyed cache, bounded full log and saved workflow under identical observable information and resource rights?

Default/null disposition: a comparator tie or win in any family block, candidate tie/loss to W1-only, any safety/rollback regression, operational infeasibility or integrity failure stops the route. Ties favor the cheaper baseline.

## 3. Stage topology

- Exactly three independent families.
- Exactly one prospectively curated independent unit per family.
- Exactly five arms per unit: `W1W2_CANDIDATE`, `W1_ONLY`, `VERSION_KEYED_CACHE`, `BOUNDED_FULL_LOG`, `SAVED_WORKFLOW`.
- Exactly 15 arm-unit executions if the stage is ever authorized.
- A2 must be semantically novel relative to A1 while returning to the A regime.
- Seeds, calls, tasks and retries do not increase N.

## 4. Frozen public comparison grammar

Within each family block, candidate versus each comparator is ordered lexicographically by:

1. lower unit loss;
2. lower A2 excess steps;
3. lower B excess steps;
4. lower stale-harm count;
5. tie = comparator win.

Every comparator match/win is retained as `OBSERVED_<KILLER>_MATCH_IN_<OPAQUE_BLOCK>`. One or more observations produce `PARK_STAGE1_NONDOMINANCE / STOP`. Strict candidate wins against every comparator in every block plus zero safety/integrity failure may produce only `ADVANCE_TO_STAGE2_DESIGN / NO_MET / NEW_PREREG_REQUIRED`.

## 5. Closed dispositions

Allowed:

- `KILL_CURRENT_IMPLEMENTATION / SAFETY_REGRESSION`
- `INVALID`
- `PARK_STAGE1_NONDOMINANCE / STOP`
- `PARK_INSUFFICIENT_FEASIBILITY / STOP`
- `ADVANCE_TO_STAGE2_DESIGN / NO_MET / NEW_PREREG_REQUIRED`

Forbidden:

- `MET`, `NARROW_MET`, `REDUCES_TO_*`, positive result, Product/value evidence, general online-learning evidence, autonomy evidence or release readiness.

## 6. Strongest-killer selection for a future disjoint Stage 2

Among `VERSION_KEYED_CACHE`, `BOUNDED_FULL_LOG`, `SAVED_WORKFLOW` only:

1. lowest mean family-block unit loss;
2. lowest mean A2 excess steps;
3. lowest mean B excess steps;
4. lowest measured direct resource cost;
5. fixed tie order `VERSION_KEYED_CACHE`, `SAVED_WORKFLOW`, `BOUNDED_FULL_LOG`.

The selected id may be emitted only after the global seal. It creates no Stage 1 inference and is usable only as a fixed comparator on new disjoint Stage 2 units.

## 7. Five-bundle admission matrix

| Bundle | Current state | Missing acceptance evidence | Fail-closed effect |
|---|---|---|---|
| B1 `DESIGN_AUTHORITY_BUNDLE` | `PARTIAL_UNACCEPTED` | exact prereg review, SESOI rationale, final role-separation and route-cast receipt | deny experiment implementation |
| B2 `SAMPLING_INFORMATION_BUNDLE` | `UNBOUND` | candidate-blind frame, ≥3 independent families, novelty/difficulty receipts, observable-information and construction commitments | deny experiment implementation/freeze |
| B3 `ARM_TREATMENT_BUNDLE` | `UNBOUND` | exact five-arm treatment, information/resource parity and liveness; legacy code has no acceptance | deny experiment implementation/freeze |
| B4 `SCORER_CUSTODY_BUNDLE` | `UNBOUND` | external non-LLM service identity/digest, private egress proof, global seal and closed output | deny experiment implementation/freeze/run |
| B5 `EXECUTION_INTEGRITY_BUNDLE` | `UNBOUND` | exact manifest, order/blinding, C7 bindings, one-shot CAS and external freeze/run receipts | deny freeze/run |

Bundle absence cannot be replaced by self-signed values, empty defaults, green tests or founder narrative.

## 8. Private custody prohibition

Keys, hidden identities/mappings, hidden manifests/tests/outcomes, mechanical paths, pre-seal arm labels and scorer internals never enter an LLM, reviewer, chat, agent tool or ordinary CI transcript. Any breach creates an immutable incident and permanently denies retry for that opened package.

Before global seal, the private service may emit only predeclared public commitments, nondirectional aggregate eligibility counts and integrity booleans. After global seal it may emit only the closed public score schema. Unknown fields fail closed.

## 9. Missing-data and one-shot rules

- No unit replacement after any directional output.
- Baseline liveness failure blocks freeze; the baseline is not dropped.
- Exhausted symmetric operational retries become prefrozen `PARK_INSUFFICIENT_FEASIBILITY` or `INVALID`, never candidate advantage.
- After hidden mount or first execution: no re-key, reseed, substitution, threshold/arm/provider change or selective rerun.

## 10. Current adjudication

`EXPERIMENT_IMPLEMENTATION_DENIED`: B1 is unaccepted and B2-B5 are unbound. No arm/candidate/baseline/scorer/freezer/executor code, freeze or result run is authorized. Independent review may separately return `QUALIFICATION_SCAFFOLD_CAST_APPROVED`, which opens only the five public files named in the Goal Card while retaining `PREREG_REVISE / NOT_IMPLEMENTATION_READY / NOT_FROZEN / NOT_RUN`.
