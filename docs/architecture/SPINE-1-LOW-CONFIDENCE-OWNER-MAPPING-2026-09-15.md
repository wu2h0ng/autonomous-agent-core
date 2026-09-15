# SPINE-1 Low-Confidence Owner Mapping (donor os_core → monorepo owner)

> Status: `REVISION_2 / RECOMMENDATION_ONLY / NOT_ACCEPTED`
> Date: 2026-09-15
> Donor pin: `aaea36c694adb04664ff30fddccb43c2eb6a6614`
> Scope: the 14 `EXTRACT_TO_PACKAGE` manifest entries marked `confidence: low`
> Authorities: `docs/architecture/SPINE-1-DONOR-OWNER-COMPLETENESS-MANIFEST.yaml`,
> `docs/architecture/SPINE-1-RETIREMENT-READINESS-2026-09-15.md`

> **Correction notice (2026-09-15).** Revision 1 of this document over-claimed
> `DROP_SUPERSEDED` for most rows. An independent subagent review ("subagent review round 1")
> checked each donor module against the *actual* monorepo owner code and found that several claimed
> owners do not exist. Verified counter-evidence (reproduced by the drafter):
> `grep -rE "UsageStore|UsageEvent|QuotaGate" packages apps` → none;
> `grep -rE "ChoiceSet|AutoExecutionPolicy|PolicyApprovalRecord" packages` → none;
> `srl_audit.py` has no hashing/chain; donor `trusted_loop.py:1769 _assert_grounded` is a
> non-bypassable SQL-Safety+EvidenceChain invariant with no manifest entry.
> Revision 2 below replaces the recommendations; the manifest
> `low_confidence_recommendations` block now carries a `review_verdict` per row.

## Corrected recommendation table

| # | Manifest id | donor module | Verdict | Correct action |
|---|---|---|---|---|
| 1 | D-OSCORE-MODELGATEWAY | `model_gateway/` | CONFIRMED_DROP_SUPERSEDED | drop; owner `os_core/provider.py` + `contracts/provider.py` |
| 2 | D-OSCORE-TRACE | `trace/`, `operation_trace/` | CONFIRMED_DROP_SUPERSEDED | drop; owner `os_core/event_store.py` + `external_boundary.py` + `operator_metrics.py` |
| 3 | D-OSCORE-TENANT | `tenant/` | **PARTIAL_NO_REAL_OWNER** | identity is owned; the **tenant metadata store** (`display_name/status/config`) is unowned → `EXTRACT_TO_PACKAGE` or recorded reduction |
| 4 | D-OSCORE-USAGE | `usage/`, `quota_gate.py` | **NO_REAL_OWNER** | `EXTRACT_TO_PACKAGE`. `contracts/resource.py` is a static per-action budget and `srl_budget_ledger.py` is an SRL help budget — neither is rolling tenant metering |
| 5 | D-OSCORE-WORKFLOW | `workflow.py`, `workflow_store.py` | **NO_REAL_OWNER** | `EXTRACT_TO_PACKAGE`. `contracts/workflow.py` is a DAG IR; `graph_scheduler.py` is topo-sort. No `WorkflowInstance`/delegate/escalate/timeout |
| 6 | D-OSCORE-TRUSTEDLOOP | `trusted_loop.py` (2119 L) | **MISCLASSIFIED_DOMAIN + NO_REAL_OWNER** | `SPLIT`: domain orchestration → `EXTRACT_TO_DOMAIN_PACK`; unique generic pieces → `EXTRACT_TO_PACKAGE`. **MUST NOT be dropped silently** (see BLOCKER) |
| 7 | D-OSCORE-POLICY | `policy_engine.py` | **MISCLASSIFIED_DOMAIN** | `EXTRACT_TO_DOMAIN_PACK` for R4/R5; the policy registry + `PolicyApprovalRecord` lifecycle needs an explicit owner (`governance.py` has only a request-level gate) |
| 8 | D-OSCORE-APPROVAL | `approval_lite/`, `approval_router.py` | **PARTIAL_NO_REAL_OWNER** | `EXTRACT_TO_PACKAGE`: choice-set, rubber-stamp analytics, approval-context resume. Digest-bound single-step approval already in `action_pipeline.py` |
| 9a | D-OSCORE-ACTIONGOV(a) | `action_governance/`, `action_proposal/`, `operation_state_machine.py` | CONFIRMED_DROP_SUPERSEDED | drop; owner `action_pipeline.py` + `proposal_engine.py` + `run_state.py` |
| 9b | D-OSCORE-ACTIONGOV(b) | `consequence_preview.py` | **NO_REAL_OWNER** | `EXTRACT_TO_PACKAGE` or explicit reduction (founder call) |
| 10 | D-OSCORE-SNAPSHOT | `snapshot_store/` | CONFIRMED_DROP_SUPERSEDED | drop; recovery/compensation owned by `contracts/runtime.py` + `capability.py`; connector-keyed state → domain pack |
| 11 | D-OSCORE-CORRIGIBILITY | `corrigibility/` | **CONFIRMED_DROP_SUPERSEDED_WITH_GAP** | halt/resume/epochs owned by `governance.py`; **tamper-evident hash-chained audit is unowned** → `EXTRACT_TO_PACKAGE` or recorded reduction |
| 12 | D-OSCORE-AGENTRUNTIME | `agent_runtime/` (1037 L) | **PARTIAL_NO_REAL_OWNER** | `EXTRACT_TO_PACKAGE`: `ToolRegistry`/`ToolSpec`, checkpoint-resume, `StructuredOutputValidator`, redacting trace writer. Loop + capability broker already owned |
| 13 | D-OSCORE-INIT | `os_core/__init__.py` | CONFIRMED_DROP_SUPERSEDED | drop; owner `os_core/__init__.py` |
| 14 | D-EXAMPLES | `examples/**` | CONFIRMED | `DROP_OPERATIONAL` |

## Severity findings (carried from review round 1)

- **BLOCKER — grounding invariant (row 6).** Donor `trusted_loop.py:1769 _assert_grounded`
  ("every formal answer/action MUST pass SQL Safety AND EvidenceChain completeness", raising
  `GroundingInvariantViolation` at `:634`, `:1525`, `:1799`) is a security invariant. No manifest
  entry captures it; it must get an explicit owner (domain pack or `EXTRACT_TO_PACKAGE`) before any
  `DROP_SUPERSEDED` is accepted.
- **MAJOR** — row 4 usage/quota; row 5 BPM workflow; row 7 policy-approval lifecycle; row 8
  choice-set/analytics/resume; row 11 hash-chained audit; row 12 tool registry/checkpoint-resume.
  Each is a real capability with no monorepo owner; `DROP_SUPERSEDED` would lose it.
- **MINOR** — row 3 tenant metadata registry (may be app-layer).
- **MISCLASSIFICATION ORDER:** donor rows 6 and 7 are domain-flavored (Metric/SQL/DataProduct/
  business-action). Per `AGENTS.md` §3 they must land in `domain_packs/data_agent`, not
  `packages/os_core`. Revision 1 named `packages/*` owners for them — internally inconsistent.

## Net effect (corrected)

- Real `DROP_SUPERSEDED`: rows **1, 2, 9a, 10, 13, 14** only (6 of 14).
- Remaining rows need `EXTRACT_TO_PACKAGE` / `EXTRACT_TO_DOMAIN_PACK` or an explicit,
  founder-recorded **capability reduction** — they cannot be silently dropped.
- A tracked gap remains: `D-SDK` target `packages/sdk` does not exist in the monorepo
  (`--strict` reports `missing targets: 1`), so the donor SDK needs a create-or-drop decision.

## Decision requested

Founder/CTO: for each row choose one of `DROP_SUPERSEDED` / `EXTRACT_TO_PACKAGE` /
`EXTRACT_TO_DOMAIN_PACK` / `CAPABILITY_REDUCTION_RECORDED`. The BLOCKER row (row 6) and the
domain rows (6, 7) require an explicit owner before any retirement. Code extraction and retirement
remain separate founder-gated execution steps.
