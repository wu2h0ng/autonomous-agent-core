# ADR-0017: EvidenceChain confidence is derived and explained (freshness · rows · template), not asserted

- Status: **DRAFT / Proposed — awaiting CTO gate. Not merged, not pushed.**
- Date: 2026-07-10
- Layer: deployment (product runtime contract + evidence chain + public run/report surface + eval gate)
- Release state: written under `DEPLOYMENT_PUSH: HOLD`; this ADR authorizes nothing about `origin/main`,
  tags, product-main promotion, or external claims. Product-main promotion is a separate CTO gate
  (PR-34-style).
- Slice: P2-C (test-first) built ON TOP of P2-A + P2-B head `a2daff7`, branch
  `feat/p2c-evidence-confidence-derivation-20260710`.
- Relation: strengthens the EvidenceChain (the "evidence, not data forwarding" mandate, repo CLAUDE.md
  #15) by making the confidence number **earned from observable inputs**. Consistent with ADR-0012
  (R4/R5 default proposal-only — unchanged), the OS-Core domain-independence boundary (#3/#15/#18), and
  the anti-pseudo-implementation / "asserted not earned" constitution boundaries (#12/#15/#16).

## Context

EvidenceChain confidence was a **hard-coded constant**: in
`packages/os_core/src/agent_os_core/evidence_chain/__init__.py` the builder set
`confidence = 0.55` when `row_count == 0` else `confidence = 0.82`. Only row-count-zero was considered;
source freshness and template verification were not inputs at all. A confidence a downstream human or
policy reads to weigh an answer was therefore **asserted, not earned** — exactly the pattern the
constitution forbids (a number that is the same regardless of how fresh, how sparse, or how verified the
underlying answer is). The number was also **unexplainable**: nothing recorded *why* it was what it was.

We want confidence to be **derived from observable inputs and explainable** — while explicitly NOT adding
a learned/statistical/probabilistic model. Learned calibration is a separately-gated future capability.
This slice delivers a transparent, bounded rule the human can audit.

## Decision

### 1. Confidence is derived from three observable inputs and records them

`confidence = f(source_freshness, row_count, template_verified)` where each input is an explicit
**bounded factor** in `[0, 1]` and each unmet safety condition applies a **cap** (never a silent high
default). The rule lives in OS Core (`agent_os_core.evidence_chain.derive_confidence`) and is
domain-independent — it reads only generic freshness / row / template-verification signals, never
Customer-0 semantics. Calibration stays `rule_based`.

The contributing inputs are recorded on a new typed `agent_os_contracts.ConfidenceInputs`, attached to
`ConfidenceScore.inputs`, so the scalar is **explainable and recomputable** from its recorded inputs:
`{row_count, template_verified, freshness_known, freshness_within_tau, source_age_seconds,
freshness_tau_seconds, freshness_factor, row_count_factor, template_factor, flags}`.

### 2. The transparent bounded rule

```
score = clamp( BASE(0.95) · freshness_factor · row_count_factor · template_factor )   # each factor ∈ [0,1]
      then min() with every applicable CAP, then max() with the zero-row FLOOR, clamped to [0.05, 0.97]
```

| input | factor | cap / floor + flag |
|---|---|---|
| freshness unknown (`source_age_seconds is None`) | 0.60 | cap **0.60**, flag `freshness_unknown` (never defaults high) |
| freshness within τ (`age ≤ τ`) | 1.0 | — |
| freshness borderline (`τ < age ≤ τ·1.10`) | 0.85 | — (still consistent) |
| freshness stale (`age > τ·1.10`) | `clamp(τ/age, 0.30, 1.0)` | cap **0.50**, flags `stale`, `tau_inconsistency` |
| no stated τ but age known | 1.0 | flag `freshness_tau_unspecified` (no claim to violate) |
| template verified | 1.0 | — |
| template unverified/absent | 0.60 | cap **0.55**, flag `unverified_template` |
| `row_count == 0` | 0.0 | floor **0.30**, flag `no_rows` (+ "no rows" limitation preserved) |
| `row_count ≥ 1` | `0.60 + 0.40·min(n,10)/10` | flag `low_row_count` when `n < 10` |

τ (the stated recency bound the answer claims) is parsed from `MetricContract.quality_contract.freshness`
by `parse_freshness_to_seconds` (`"24h"`, `"7d"`, `"30m"`, bare seconds, or `hourly/daily/weekly/monthly`;
unrecognized → `None` = unspecified). Every limitation implied by a fired flag is recorded on the
EvidenceChain, and the `Claim.confidence` label is derived from the score (`high ≥ 0.70`, `medium ≥ 0.40`,
else `low`).

### 3. τ-consistency boundary at the DataProduct → EvidenceChain seam

The actual source freshness (`QueryResult.source_age_seconds`, a new optional field the provider/executor
populates; `None` = unknown) meets the contract's stated τ inside the builder — the DataProduct →
EvidenceChain seam. When the actual freshness violates τ beyond a 10% tolerance, the evidence **flags and
caps** (records a `tau_inconsistency` limitation and caps at 0.50) rather than blocking — advisory evidence
per this slice; blocking is reserved for a seam contract that demands it. Missing freshness caps at 0.60
and flags `freshness_unknown` — it is **never** treated as fresh.

### 4. The derived confidence + its inputs are on the public evidence surface

The scalar has always been observable at `user_result.analysis.confidence` (and `decision.confidence`).
This slice surfaces the inputs on the **same** surface: `user_result.analysis.confidence_inputs`
(typed `UserResultConfidenceInputs`), populated in `outcome_service._build_user_result_artifact` from
`evidence.confidence_score.inputs`, so the number is auditable and testable end-to-end, not an internal
field. The API contract grew, so `openapi.json` and the frontend `schema.d.ts` were regenerated.

### 5. A bypass-detecting eval dimension + distribution regression

The golden threshold report gains a per-case `confidence_derivation` dimension (threshold 1.0): each
case's confidence must be **recomputable** from its recorded inputs via the same rule — a hard-coded
constant carries no inputs (or an inconsistent score) and fails. The golden harness now varies
per-case source freshness against a stated τ, and a regression test asserts the confidence
**distribution** across the 20 golden intents is non-constant and no longer uniformly high (if everything
collapses back to a single constant, both fail).

## Boundaries honored

- **No learned model.** Calibration stays `rule_based`; the rule is a transparent bounded arithmetic of
  observable inputs. No training, no probability, no statistical calibration (anti-goal, deferred).
- **OS Core domain-independent.** The rule and the freshness parser read only generic signals; no
  Customer-0 logic. The freshness parser and factor constants are business-neutral.
- **R4/R5 proposal-only unchanged.** This slice touches evidence confidence only, not action execution.
- **All formal answers still pass SQL Safety + EvidenceChain.** The builder still asserts a complete,
  typed EvidenceChain; the change only alters the confidence scalar, its inputs, and the limitations.
- **Every behavioral change has a bypass-detecting test** (relational, cap, flag, recomputation, and
  distribution assertions), each confirmed to FAIL against the constant-confidence code before implementation.

## Engineering reality gates

- **Entry point:** `EvidenceChainBuilder.build()` (the Trusted Loop's evidence step) calls
  `derive_confidence(...)`; the result reaches `POST /runs` and `GET /runs/{trace_id}/report` via
  `user_result.analysis.{confidence,confidence_inputs}`.
- **Contract:** consumes `QueryResult.source_age_seconds`, `MetricContract.quality_contract.freshness`,
  `MetricContract.verified_queries`/`QueryPlan.source_template`; produces `ConfidenceScore.inputs`
  (`ConfidenceInputs`) and `UserResultConfidenceInputs`.
- **Failure mode:** unknown freshness → cap 0.60 + `freshness_unknown`; τ violated → cap 0.50 +
  `tau_inconsistency`; unverified template → cap 0.55 + `unverified_template`; zero rows → floor 0.30 +
  `no_rows`. None default high.
- **Test validity:** tests assert stale<fresh, small-N<full-N, caps, flags, and recompute-consistency;
  a constant return fails each. The eval dimension fails if inputs are absent or the score is inconsistent.
- **Observability:** the derivation inputs are recorded on the EvidenceChain and surfaced on the public
  analysis surface + eval report.
- **Product/process boundary:** this is **product runtime behavior** (the EvidenceChain a client reads),
  not a development-process control.

## Consequences

- Real runs whose provider does not yet report `source_age_seconds` are **honestly capped** at
  `freshness_unknown` (≈0.57 for a full/verified answer) instead of the old asserted 0.82 — the correct,
  conservative default until a provider surfaces real recency, which then lifts the cap. Wiring real
  provider freshness is follow-on work, not this slice.
- `ConfidenceScore.inputs` is not persisted by the mapper (only the scalar `evidence.confidence` is, as
  before); the live run/report surface is built fresh from the in-memory result, so `confidence_inputs`
  is available there. Persisting the typed inputs is a possible follow-on.
- One existing assertion (`test_builder_populates_typed_fields` exact limitation count) and one eval
  threshold-file fixture were updated to reflect the intentional behavior change; no gate was weakened.

## Alternatives considered

- **Keep a constant, richer copy.** Rejected: still asserted, still unexplainable.
- **Learned/statistical calibration.** Rejected for this slice (anti-goal): opaque, needs training data
  and a separate gate; the point here is *earned + explainable*, not ML.
- **Block on τ violation.** Rejected as the default: advisory flag-and-cap preserves the answer with an
  honest limitation; blocking is reserved for a seam contract that demands it.
- **Carry freshness via lineage/data-product metadata dicts.** Deferred in favor of a typed
  `QueryResult.source_age_seconds` — the freshness of the actual returned data, closest to the observable
  and deterministic to test; the ADR notes it represents the provider/source recency observation.
