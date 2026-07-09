# ADR-0015: Approval rubber-stamp analytics + the `revise` decision outcome

- Status: **DRAFT / Proposed — awaiting CTO gate. Not merged, not pushed.**
- Date: 2026-07-10
- Layer: deployment (product runtime contract + approval decision surface + analytics read surface)
- Release state: written under `DEPLOYMENT_PUSH: HOLD`; this ADR authorizes nothing about `origin/main`,
  tags, product-main promotion, or external claims. Product-main promotion is a separate CTO gate.
- Slice: P2-A (test-first) off product main `1bdf280`, branch
  `feat/p2a-approval-analytics-revise-20260710`.
- Relation: makes ADR-0014's human choice-set mechanism **falsifiable in production** (RR-0050 §7).
  Consistent with ADR-0009 (seam-facing `candidate_actions`), ADR-0012 (R4/R5 default proposal-only),
  and the OS-Core domain-independence boundary (repo CLAUDE.md #3/#15).

## Context

ADR-0014 gave an approval-required proposal a human-facing choice set: `>=2` alternatives with exactly
one recommendation, or an explicit `single_option_rationale`. But the approval lifecycle only recorded
`approved` / `rejected` — it could **not** show whether the operator ever *modified* the recommended
option. Without that signal there is no way to measure rubber-stamping: an operator who blindly accepts
every pre-baked recommendation and one who genuinely deliberates produce identical records. The
anti-rubber-stamp mechanism is therefore unfalsifiable in production.

RR-0050 §7 requires the rubber-stamp rate to be **observable per tenant/risk** so the ADR-0014 mechanism
can be checked against real operator behavior (e.g. a `selection_concentration` stuck at `1.0` across a
tenant is evidence the choice set is decorative, not load-bearing).

## Decision

### 1. A derived, non-self-reported decision outcome (the `revise` signal)

`ApprovalRecord` gains `decision` (`approved_recommended` | `approved_revised` | `rejected` |
`escalated`, typed as `ApprovalDecision` in `agent_os_contracts`) and `selected_action` (the action the
approver actually approved). It also snapshots `recommended_action`, `risk_level`, and `created_at` at
proposal time so the decision path and analytics are self-contained after the (transient) proposal and
approval-resume context are gone.

The decision entry point (`ApprovalLiteRuntime.decide` → wrapped by
`TrustedLoopRuntime.record_approval_decision`) takes a **coarse operator intent**
(`approve` | `reject` | `escalate`) plus an optional `selected_action`. The fine-grained classification
is **DERIVED**, never taken from the operator's word:

- `approved_recommended` ⇔ `selected_action == recommended_action` (or omitted). Potential rubber-stamp.
- `approved_revised` ⇔ `selected_action` is a **different, in-choice-set** alternative. A `revise`.

Deriving (rather than trusting a self-labelled outcome) is what makes `selection_concentration` a
measurement instead of a self-report — the whole point of the falsifier.

### 2. Choice-set-membership guard on a revise

A `revise` naming an action **not** in the proposal's surfaced `alternatives` is refused with
`BlockCode.CHOICE_SET_VIOLATION` (reusing the ADR-0014 invariant's spirit). At the lifecycle layer this
is a typed `ChoiceSetViolationError` carrying the block code (so `approval_lite` need not import the
runtime); `record_approval_decision` translates it into a `TrustedLoopBlock` and a persisted `blocked`
Trace. A revise must pick a real surfaced alternative — otherwise the choice-set audit trail is fiction.

### 3. `ApprovalAnalytics` read surface, derived (not a parallel counter)

New typed contract `ApprovalAnalytics{tenant_id, window, risk, counts{approved_recommended,
approved_revised, rejected, escalated}, total, modify_rate, selection_concentration}`:

- `modify_rate = approved_revised / (approved_recommended + approved_revised)` (`0.0` if no approvals).
- `selection_concentration = approved_recommended / (approved_recommended + approved_revised)`
  (`1.0` = pure rubber-stamping; `0.0` if no approvals).

New endpoint `GET /analytics/approvals?tenant=&risk=&window=` DERIVES it by scanning tenant-scoped
`ApprovalRecord`s (paginated, store-agnostic). There is **no second mutable counter store** to drift.
`window` supports `all` (default) and `<N>h` / `<N>d` / `<N>w`, filtered against `created_at`.

### 4. Trace + RBAC

Each decision writes a queryable `approval_decision` Trace event (outcome + selected_action + whether it
was a revise). The analytics read and the decision write are **admin/operator-only**
(`analytics:read`, `approvals:decide` on the internal principal); the `external_report` and `viewer`
principals do not hold them, so deliberation / modify-rate signal never leaks to an external audience.

`POST /approvals/{approval_id}/execute` is unchanged (execute = the approved action). Recording a
`decision` is a separate, explicit surface; an executed-without-explicit-decision approval simply has
`decision == None` and is not counted in analytics.

## Boundaries preserved

- **OS-Core domain independence.** Analytics is generic counting over typed records — no Customer-0 /
  content-commerce / domain semantics in Core. The runtime never invents or reorders alternatives.
- **R4/R5 proposal-only** is unchanged; this slice touches only how a decision is *recorded* and
  *measured*, never what may auto-execute.
- **C7 / corrigibility** unchanged; decisions are observed into the shell audit when a shell is wired.
- **Backward compatibility.** All new `ApprovalRecord` fields default to `None`; pre-P2-A payloads
  deserialize unchanged (JSON `payload` column — no schema migration). Legacy `approve`/`reject` preserve
  the snapshot fields and leave `decision` unset.

## Contract changes (surface)

- `agent_os_contracts`: `+ApprovalDecision` (StrEnum), `+ApprovalDecisionCounts`, `+ApprovalAnalytics`.
- `agent_os_core.approval_lite`: `ApprovalRecord` `+decision, +selected_action, +recommended_action,
  +risk_level, +created_at`; `+ChoiceSetViolationError`; `ApprovalLiteRuntime` `+decide`, `+analytics`.
- `agent_os_core.trusted_loop.TrustedLoopRuntime`: `+record_approval_decision`; snapshots
  `recommended_action`/`risk_level` into the pending approval.
- HTTP: `+POST /approvals/{approval_id}/decision`, `+GET /analytics/approvals`; scopes
  `+approvals:decide`, `+analytics:read` (internal principal only). `openapi.json` + frontend
  `schema.d.ts` regenerated.
- Persistence: `approval_{to,from}_payload` extended for the five new fields (JSON payload; no migration).

## Falsifier use

`selection_concentration` per tenant/risk is the production probe for ADR-0014. Concentration pinned at
`1.0` (with non-trivial volume) falsifies the claim that the surfaced choice set changes operator
behavior; a `modify_rate > 0` that tracks genuine risk is the corroborating positive signal. This ADR
delivers the **measurement surface**; interpreting the collected rates against the mechanism is a later
analysis step, not a claim made here.
