# SPINE-1 Remaining Owner Adjudication — deep analysis (revision 2)

> Status: `RECOMMENDATION_ONLY / REQUIRES_FOUNDER_SIGNOFF (reductions)`
> Date: 2026-09-15
> Revision 2 supersedes the first pass: after checking for real consumers and native coverage, the
> recommendation for most rows flips from IMPLEMENT to REDUCE/SUPERSEDE.

## Evidence base

- **No consumers** in the monorepo (`packages/os_core/src`, `packages/contracts/src`, `apps`):
  `ToolRegistry`, `CheckpointStore`, `StructuredOutput`, `ToolSpec`, `QuotaGate`, `approval_workflow`
  → **0 references each**; `UsageStore` → 0.
- **Native coverage**: capabilities ARE the tools (`capability.py` `specs()` / `CapabilitySpec`);
  durable resume/checkpoints exist (`event_store.py`, `recovery.py`, `agent_loop.resume_pending_approval`);
  policy/authority exist (`governance.py`, `action_pipeline.py`); external boundary exists
  (`external_boundary.py`, provider/connector contracts).
- **Product blueprint**: tenancy, workflow authoring and ecosystem interfaces are the *later*
  "Operational body" (#3), and "workflow orchestration as the product identity" is explicitly
  superseded. The core product is Mandate/Outcome/governed action/outcome compounding.
- **AI-Agent constitution §10**: module existence, unused adapters and pseudo-implementation do not
  count as progress. Porting code with no consumer is a net negative.

## Per-item verdict (revision 2)

| # | Entry | Verdict | What actually happens |
|---|---|---|---|
| 1 | `TRUSTEDLOOP` | **REDUCE** | Its load-bearing invariants are already implemented natively (grounding, consequence preview, choice-set, exec-time recheck, approval, adoption, corrigibility). The 2119-line orchestrator is superseded by `agent_loop`+`action_pipeline`+`capability`+`governance`. Record: no monolith ported. |
| 2 | `POLICY` | **REDUCE (engine) / DONE (lifecycle)** | ADR-0012 keeps R4/R5 proposal-only; no tenant auto-exec consumer exists. The version-bound, single-use approval-record lifecycle (the valuable part) is already implemented (`policy_approvals.py`). The rule registry/engine is unused → reduce until a named auto-exec consumer exists. |
| 3 | `TENANT` | **REDUCE** | Tenant identity is server-bound in core (`authority.py`, `protocol_ingress.py`); metadata registry is app/composition-layer and has no consumer. |
| 4 | `USAGE` | **REDUCE** | Rolling tenant metering + quota has no consumer; `ResourceBudget` (per-action) and `srl_budget_ledger` already cover current budget needs. Implement later only when a real tenant/quota consumer exists. |
| 5 | `WORKFLOW` | **REDUCE / PARK** | No BPM consumer (`approval_workflow` = 0). Monorepo uses single-step digest-bound approval + `HelpRequest` escalation; the DAG `WorkflowGraph` is the execution IR. Revisit if a multi-step human-approval product path is named. |
| 6 | `MCP` | **REDUCE (for now)** | No MCP consumer; tool/connector boundaries are covered by capability/provider/connector contracts. Add an MCP gateway when an interop consumer exists. |
| 7 | `AGENTRUNTIME` | **REDUCE (superseded)** | `ToolRegistry`/`ToolSpec` ≈ `capability.specs()`; `CheckpointStorePort`/resume ≈ `event_store`+`recovery`+`agent_loop` resume; `StructuredOutputValidator` ≈ typed contracts + evaluator. The 1036-line runtime shell duplicates the native spine. |
| 8 | `CONTRACTS-GENERIC` | **REDUCE / SUPERSEDE** | `governance_decision_seam.py` **done** (core); `configuration.py`/`observability.py` ported. Donor `workflow.py` and `domain_pack.py` are **superseded** by core `workflow.py` (`WorkflowGraph`) and `domain.py` (`DomainPackManifest`); `usage.py`/`mcp_gateway.py`/`heavy_infrastructure.py`/`causal_discovery_seam.py` have no consumer. |

## Net effect

- **Load-bearing Data Agent domain capability is preserved** (batches 1-7: metric contracts, query
  runtime, semantic/NL, knowledge/retrieval, evidence, alerts/dashboard/feedback/adoption,
  corrigibility, approval lifecycle, action connectors, governed-decision seam).
- The remaining 8 are **enterprise/Optional-body plumbing** with no consumer, partly covered natively.
  Porting them now would add unused code — prohibited by §10.
- Recommended disposition: record all 8 as **founder-accepted capability reductions** (not silent
  drops), each with the note "implement on demand when a named consumer exists".

## What this needs

Founder/CTO: accept the reductions (rows 1-8). On acceptance, the manifest entries move from
`EXTRACT_*` (gap) to a `REDUCE_ACCEPTED_BY_FOUNDER` terminal disposition, and the retirement gate can
legitimately close without porting dead plumbing. Everything else (load-bearing domain) is already on
the branch.
