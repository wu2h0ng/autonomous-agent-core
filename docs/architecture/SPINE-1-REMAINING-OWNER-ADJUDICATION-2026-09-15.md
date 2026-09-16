# SPINE-1 Remaining Owner Adjudication — implement vs reduce

> Status: `RECOMMENDATION_ONLY / NOT_ACCEPTED`
> Date: 2026-09-15
> Basis: subagent review rounds 1-2 (per-module verdicts) + direct recon of donor API vs monorepo
> owners; branch `codex/spine1-donor-extraction-20260915`.

For each remaining EXTRACT entry: **IMPLEMENT** (port/re-implement a real capability with a real
consumer) or **REDUCE** (record an explicit capability reduction — do not add unused code, per
AGENTS.md §10).

| # | Entry | Donor (API, size) | Monorepo owner today | Verdict | Rationale |
|---|---|---|---|---|---|
| 1 | `D-OSCORE-TRUSTEDLOOP` | `TrustedLoopRuntime` + ~10 imports, 2119 L | discrete capabilities already ported: `grounding.py`, `consequence_preview.py`, `approval_choice.py`+`approval_lite.py`, `adoption.py`, `corrigibility.py`; exec-time recheck lives in `capability.py`/`action_pipeline.py` (parity test added) | **REDUCE** | the monolith itself is not portable without its DROP_SUPERSEDED graph (`operation_trace`, `snapshot_store`, `action_governance`, `action_proposal`). Its unique, valuable pieces are **already implemented**; record the reduction of the orchestration shell explicitly. |
| 2 | `D-OSCORE-POLICY` | `PolicyEngine` + `AutoExecutionPolicy` registry + `PolicyApprovalRecord` lifecycle, 446 L (needs `operation_trace`) | `governance.py` PolicyKernel is a request-level gate only; `configuration.py` (`AutoExecutionPolicy`/`PolicyApprovalRecord`) + `policy_approvals.py` ported | **IMPLEMENT (domain pack)** | R4/R5 policy is domain semantics. Port the registry + approval-record lifecycle, making the `operation_trace` dependency optional. |
| 3 | `D-OSCORE-TENANT` | `Tenant`/`TenantStorePort`/`InMemoryTenantStore`, 96 L (metadata registry) | identity is server-bound in `contracts/authority.py` (`PrincipalIdentity`) + `protocol_ingress.py`; no tenant **metadata** store | **REDUCE** | tenant metadata is an app/composition concern; core already owns identity; no live consumer. Keep as an app-layer note, not core code. |
| 4 | `D-OSCORE-USAGE` | `UsageStorePort`/`InMemoryUsageStore` + `quota_gate.py`, 80+73 L | none (`contracts/resource.py` is a static per-action budget; `srl_budget_ledger.py` is an SRL help budget) | **IMPLEMENT (packages/os_core)** | generic rolling tenant metering + quota gate is a real, domain-neutral primitive with no owner. |
| 5 | `D-OSCORE-WORKFLOW` | `WorkflowRuntime` BPM multi-step approval (delegate/escalate/timeout), 436 L | `contracts/workflow.py` is a DAG IR + `graph_scheduler.py` topo-sort (different concept) | **IMPLEMENT (packages/os_core)** *if a product consumer is named*; else **REDUCE** | a DAG scheduler is not a BPM chain. Decide by whether a product path needs multi-step human approval; do not add unused engine code. |
| 6 | `D-OSCORE-MCP` | `McpGatewayRegistry`/`McpToolRouter` + risk/tenant/scope/pause enforcement + audit, 310 L | none | **IMPLEMENT (packages/os_core)** | generic external-boundary primitive with no owner; useful for the connector boundary. |
| 7 | `D-OSCORE-AGENTRUNTIME` | `AgentRuntime`, `ToolRegistry`/`ToolSpec`, checkpoint-resume, `StructuredOutputValidator`, redacting trace writer, 1036 L | loop + capability broker + policy gate exist (`agent_loop.py`, `capability.py`, `governance.py`); tool registry / checkpoint-resume / output validator have no owner | **PARTIAL**: IMPLEMENT the unique primitives (tool registry, checkpoint-resume, output validator); REDUCE the superseded runtime shell | keep only what the monorepo lacks; the loop/budget shell is already owned. |
| 8 | `D-CONTRACTS-GENERIC` | `observability.py`(done into domain pack), `usage.py`, `mcp_gateway.py`, `workflow.py`, `configuration.py`(done), `heavy_infrastructure.py`, `governance_decision_seam.py`(**DONE** → core), `causal_discovery_seam.py`, `domain_pack.py` | core already owns `workflow.py` (`WorkflowGraph`) and `domain.py` (`DomainPackManifest`) | **PER-FILE**: IMPLEMENT `usage.py`/`mcp_gateway.py`/`heavy_infrastructure.py`/`causal_discovery_seam.py`; **SUPERSEDE** donor `workflow.py` (core IR wins) and `domain_pack.py` (core `domain.py` wins); re-home `observability.py` to core if any core consumer appears | split the entry; do not overwrite core `workflow.py`/`domain.py`. |

## Suggested sequencing

1. IMPLEMENT (low risk, no monorepo owner): `USAGE`, `MCP`, `CONTRACTS-GENERIC` file subset.
2. IMPLEMENT (domain): `POLICY`.
3. IMPLEMENT partial: `AGENTRUNTIME` unique primitives.
4. Decided-by-consumer: `WORKFLOW` (needs a named product path).
5. REDUCE (record explicitly): `TRUSTEDLOOP` shell, `TENANT`.
6. Deferred to last: concrete `CONNECTORS`, `DOMAINPACKS`, `APISERVER-*` (integration).

## Decision requested

Founder/CTO: accept/reject per row. Rows 1/3 (and possibly 5) are **reductions**, which must be
recorded as founder-accepted capability reductions, not silently dropped. Rows 2/4/6/7/8 are
implementation work that can proceed under the existing extraction branch.
