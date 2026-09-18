# ADR-0014: Human-facing choice-set contract for approval-required proposals (anti-rubber-stamp)

- Status: **DRAFT / Proposed — awaiting CTO gate. Not implemented, not merged, not pushed.**
- Date: 2026-07-09
- Layer: deployment (product runtime contract + approval surface)
- Release state: written under PR-33 Option A `DEPLOYMENT_PUSH: HOLD`; this ADR authorizes nothing about
  `origin/main`, tags, or external claims.
- Relation: extends ADR-0009 (governed causal intervention-selection, seam-facing `candidate_actions`)
  to the **human approval surface**. Consistent with ADR-0004 (seam tighten-only), ADR-0012 (R4/R5
  default proposal-only), RR-0033 §2.5 (D8 / choice-set-collapse risk, founder-reserved bet).

## Context

1. **The blueprint locates the capability in the choice.** `docs/GOAL-BLUEPRINT.md`: the capability that
   matters lives in the governed action loop itself — *the choice of which intervention to run* — not in
   any single learning objective. A governance layer that only sees one already-chosen action exercises
   veto power, not choice power.
2. **Registered risk.** RR-0033 §2.5 registers the unresolved D8 / SD4-shadow bet: if the proposing organ
   collapses the meaningful choice set before the disposer sees it, "deterministic disposer" degrades to
   bookkeeping. The 2026-07-09 NEUMA architecture review sharpened this into the decisive rejection
   criterion (EFE argmin selects the action inside the cognitive layer; governance sees one proposal).
   Honest application of that criterion to our own product: it holds today in weakened form.
3. **Current product state (the gap).**
   - `ActionProposal.candidate_actions` (ADR-0009) exists, but it is **seam-facing**: bare string labels
     consumed by the governed-decision seam for causal selection. Default product paths
     (`ActionProposalBuilder.build`) emit **no candidates**.
   - The human approval surface (`GET /approvals/{approval_id}`, approval UI, `user_result.decision`)
     shows a single `recommended_action` + reason. The approver cannot see what else was considered,
     why it was not recommended, or whether nothing else was considered at all.
   - Nothing distinguishes "one option because the domain genuinely has one admissible action" from
     "one option because the proposer never deliberated". The two must be separable to audit collapse.
4. **External corroboration (design references only; no runtime dependency, per boundary #7).**
   - Selection-as-power governance (arXiv 2602.14606, 2026): the binding constraint is authority over
     *which options are generated, surfaced, and framed*, not action-level filtering; recommends
     presentation-gate invariants and selection-concentration metrics.
   - Organizational Control Layer (arXiv 2606.04306, 2026): approve / **revise** / block / escalate over
     candidate actions at the execution boundary.
   - SAND (OpenReview 2026): explicit deliberation over candidate actions before commitment measurably
     improves agent decisions — deliberation records are valuable even absent governance.

## Decision

Make the surfaced choice set an explicit, auditable contract property for every approval-required
proposal.

### 1. Contract (minimal, backward-compatible)

Add to `agent_os_contracts`:

```python
@dataclass(frozen=True)
class ActionAlternative:
    action: str                      # human-readable candidate action
    rationale: str                   # why it is / is not the recommendation
    risk_level: RiskLevel | None = None
    recommended: bool = False        # exactly one True when alternatives non-empty
```

Add to `ActionProposal`:

```python
alternatives: tuple[ActionAlternative, ...] = ()   # human-facing deliberation record
single_option_rationale: str | None = None         # explicit "why only one option"
```

**Invariant (fail-closed):** when `approval_required` is true, the proposal MUST carry either
`alternatives` (≥2 entries, exactly one `recommended=True`, consistent with `recommended_action`) or a
non-empty `single_option_rationale`. Proposals violating the invariant are refused at the proposal step
with a typed `BlockCode` and a trace event — they never reach `awaiting_approval`.

Non-approval proposals (R0–R2 propose-only) are exempt; fields remain optional there.

### 2. Relationship to `candidate_actions` (ADR-0009)

- `candidate_actions` stays as-is: seam-facing selection labels for the deterministic disposer.
- `alternatives` is the human-facing deliberation record. When both are present, every
  `candidate_actions` label MUST appear among `alternatives` (so the human sees at least what the
  disposer saw). The ADR-0009 rebind rule is unchanged; when the seam's `chosen_action` rebinds
  `recommended_action`, the `alternatives` `recommended` flag is rebound with it.

### 3. Surfaces

- `GET /approvals/{approval_id}` and the approval detail UI render `alternatives` (with rationales and
  risk levels), `single_option_rationale`, and the seam's `chosen_action` when present.
- `user_result.decision` gains `alternatives` and `single_option_rationale` projections (audience-aware
  redaction rules apply; external audiences receive the same redaction treatment as existing decision
  fields).
- **Presentation invariant** (borrowed from selection-as-power): alternatives are rendered in a stable
  neutral order (e.g. lexical by action id) with the recommendation flagged — recommendation is marked,
  never reordered to the top — so approver position bias is not exploitable by the proposer.
- OpenAPI snapshot regenerated; drift gate must pass.

### 4. Trace / evidence

- `action_proposal` trace event gains `alternatives_count` and `has_single_option_rationale`.
- Existing `governed_decision` event (`chosen_action`) unchanged.
- EvidenceChain is not restructured; alternatives reference the same evidence chain id.

### 5. Staged companion (separate slice, not authorized here)

Approval analytics as a rubber-stamp detector: approve / modify / reject / escalate rates per tenant and
risk level on the operator surface. ~100% unmodified approval over a window is the measurable early
signal that governance is degrading to bookkeeping. Listed here so the two slices are read as one
programme; implementation needs its own goal card.

An OCL-style **revise** outcome (approver edits the proposal into a safer alternative, recorded as a
modification) is noted as a candidate follow-up, not part of this ADR.

## Scope / non-goals — honest bounds

- **Enumerated, not self-generated.** Alternatives come from the proposer/domain (metric
  `action_candidates`, `UncertaintyDrivenProposer` driver space, or builder logic) — this ADR does not
  add open-world action generation (object-layer territory, seam-only).
- **Does not prove non-collapse.** A proposer can still enumerate strawmen. This ADR makes the surfaced
  set *visible, contractual, and measurable*; strawman detection is what the causal seam (ADR-0009
  interventional verification) and the analytics companion address. We claim auditability, not a
  solved D8.
- **No execution semantics change.** R4/R5 stay proposal-only (ADR-0012); the seam stays tighten-only
  (ADR-0004); C7 pause supremacy unchanged; approval execution path (operator key, context binding)
  untouched.
- **No new ML.** Rationales are structured text supplied by existing deterministic builders; no model
  inference is added to the control path.

## Consequences

- Positive: the approval surface exercises informed choice, not blind veto; choice-set collapse becomes
  a contract violation with a typed refusal instead of a silent default; ADR-0009's causal selection
  becomes visible to the human who signs; the D8 bet gains a product-side measurement point.
- Cost: two contract additions + one invariant check in the proposal step; builder updates to supply
  rationales on approval paths; OpenAPI snapshot regen; UI rendering; test updates. Existing
  single-recommendation behavior is preserved for non-approval paths and for empty-default construction
  in tests that do not set the new fields (invariant applies only where `approval_required=True` flows
  through the runtime proposal step).

## Tests (would fail if the contract were bypassed)

1. Approval-required proposal with neither `alternatives` nor `single_option_rationale` → refused with
   typed block + trace event; never reaches `awaiting_approval`. (Negative path.)
2. `alternatives` present but zero or two `recommended=True`, or recommendation label inconsistent with
   `recommended_action` → refused. (Consistency.)
3. Default R2 analysis path (no approval) unchanged — regression on existing tests.
4. `action_record` approval path emits either ≥2 alternatives or an explicit single-option rationale;
   assertion on the rendered approval detail payload.
5. Seam path regression: with `candidate_actions` present, every label appears in `alternatives`; on
   ALLOW-with-rebind, the `recommended` flag follows `chosen_action` (extends ADR-0009 rebind test).
6. OpenAPI: `/approvals/{approval_id}` and `user_result.decision` schema include the new fields;
   snapshot drift gate green.
7. Redaction: external-audience projection applies existing decision-field redaction rules to
   `alternatives` rationales.

## Completion gate mapping

- Entry point: `TrustedLoopRuntime` proposal step (invariant enforcement) + `GET /approvals/{approval_id}`
  + `user_result.decision` projection.
- Contract: `ActionAlternative` (new), `ActionProposal.alternatives` / `single_option_rationale`.
- Negative path: test 1/2 typed refusal.
- Bypass-detecting test: tests 1 and 5 fail if the runtime skips the invariant or hides the choice set.
- Trace/evidence update: `action_proposal` event fields; evidence chain unchanged by design.
- OS Core boundary: enforcement logic is domain-independent; alternatives content is supplied by domain
  packs / builders; no imports from domain_packs/providers/connectors into OS Core.
- OpenAPI surface: changed → snapshot regen + drift gate required in the implementing PR.

## Review routing

Touches contracts + ActionProposal behavior + OpenAPI → CTO gate required before implementation
(workspace rule: escalate contract/approval changes). Founder sign-off not required for the contract
slice itself (no cross-repo wiring, no R4/R5 change, no push), but implementation lands only behind the
normal test-first flow and stays local under the PR-33 HOLD.
