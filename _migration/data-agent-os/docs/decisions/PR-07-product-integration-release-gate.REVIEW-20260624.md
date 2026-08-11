# PR-07 Product Integration Release-Gate Review (2026-06-24)

- **Status:** REVIEW / DO NOT MERGE YET
- **Layer:** deployment / Enterprise OS product integration
- **Reviewed target:** product-integration stack through F3 live-run surface
- **Current main inspected:** `c404e1e`
- **Latest rehearsal inspected:** `codex/workspace-f3-integration-rehearsal` at `d46bd45`
- **Decision authority:** founder/CTO merge and release gates

This review does not merge, push, release, deploy, approve production UI, approve automatic R4/R5 execution, or claim external-system exactly-once / ACK confirmation / full RBAC / tenant isolation.

## 1. Verdict

```text
release_gate_status: NOT_READY
merge_gate_status: HOLD
recommended_next: RE-RUN INTEGRATION REHEARSAL FROM CURRENT MAIN c404e1e
```

The product-integration stack has useful evidence: F1/F2/F3a were merged in rehearsal at `d46bd45`, full CI passed there, and static-browser QA checked desktop and mobile behavior. That evidence is not current enough to merge now because the rehearsal base was `fb2399a`, while local `main` is now `c404e1e`.

`c404e1e` is not an ancestor of `d46bd45`. The current main includes four commits that were not covered by the F3 integration rehearsal:

```text
ad272e4 feat: enforce runtime context risk ceiling
20ed119 feat(runtime): bind checkpoint resume to call context
5022cc9 docs(runtime): record checkpoint resume boundary
c404e1e docs(security): record mcp leakage risk
```

Therefore the correct gate action is not "merge the old rehearsal". It is to create a new rehearsal from current `main` and replay:

```text
c404e1e main
  -> codex/enterprise-integration-reconcile
  -> codex/workspace-f1-contract-surface
  -> codex/workspace-f2-api-report-surface
  -> codex/workspace-f3-live-run-surface
```

## 2. Evidence Checked

- `docs/CURRENT_STATE.yaml` on local `main` at `c404e1e`
- `docs/decisions/PR-07-frontend-workspace-f3-integration-rehearsal.VERIFICATION-20260624.md` on rehearsal branch `d46bd45`
- `docs/decisions/PR-07-frontend-workspace-f3-live-run-surface.IMPLEMENTATION-LOG-20260624.md` on F3a branch `099430f`
- Git ancestry checks:
  - `git merge-base --is-ancestor fb2399a d46bd45` returned success
  - `git merge-base --is-ancestor c404e1e d46bd45` returned failure

## 3. What The Existing Rehearsal Still Proves

The old `d46bd45` rehearsal proves:

- the product stack can be mechanically applied over the earlier local main lineage;
- first-step conflicts were limited to `README.md` and `docs/CURRENT_STATE.yaml`;
- reconcile -> F1 -> F2 -> F3a merged without additional conflicts;
- `make ci` passed with `453 tests OK`, `4 skipped`, `12 eval tests OK`, ruff clean, format clean, and OpenAPI up to date;
- Playwright browser QA loaded the static prototype at desktop `1440x900` and mobile `390x900`;
- F3a `POST /runs` markers were visible and the no-API-server error path entered the bounded network state.

This is strong integration evidence, but not a current merge artifact.

## 4. Why It Cannot Be Used As The Current Merge Gate

The rehearsal does not include the current runtime and security documentation changes on main:

- runtime context `risk_ceiling`;
- fingerprint-bound checkpoint resume;
- ADR-0003 checkpoint resume documentation;
- MCP protocol-induced leakage risk-card docs.

Even if these changes are mostly runtime/docs and probably low-conflict for the static workspace prototype, release discipline cannot assume they are harmless. A merge gate must test the actual current main.

## 5. Required Re-Rehearsal

Create a fresh branch/worktree from `c404e1e` and replay the same stack.

Required verification:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Required observed gates:

- unittest/eval suite passes;
- ruff and format pass;
- OpenAPI contract drift check passes;
- conflict resolution is documented;
- if static prototype files change, run browser QA at desktop and mobile viewports;
- no horizontal overflow on mobile;
- bounded no-API-server/network error state remains fixed text, not raw response or exception body;
- no management endpoints, operator-key routes, approval-execution UI, or arbitrary-origin API-key sends are introduced.

## 6. Merge Gate Conditions

The founder/CTO can consider merge only after:

1. Fresh rehearsal is based on current `main`.
2. Conflicts are resolved with source/status docs reflecting current runtime and product stack truth.
3. CI and required browser QA pass on the fresh rehearsal.
4. A new verification record names the fresh rehearsal commit.
5. Non-claims remain intact:
   - no production UI;
   - no external release;
   - no full live golden-loop workspace claim;
   - no approval-execution UI;
   - no external ACK confirmation;
   - no external-system exactly-once;
   - no full RBAC/DLP/tenant isolation;
   - no durable arbitrary external connector recovery;
   - no automatic R4/R5 execution.

## 7. Release Gate Conditions

Even after merge, release remains blocked until a separate release review verifies:

- user-facing run flow against an actual API server, not only static fallback;
- configured auth matrix and external-report projection behavior;
- redaction for external/public and external/non-public paths;
- trace/evidence display safety;
- action proposal review-only behavior for R4/R5;
- deployment environment and secret handling;
- rollback and support plan.

## 8. Product Capability Boundary

The F1/F2/F3 stack moves the prototype toward a user-facing data-agent workspace:

- F1: DataProduct / KnowledgeAsset candidate visibility;
- F2: read-only report projection from `GET /runs/{trace_id}/report`;
- F3a: limited `POST /runs` submission and `RunResponse.user_result` rendering.

That is product progress, not autonomous-core research evidence and not workflow-runtime capability. It supports the deployment-layer path toward analysis/report/dashboard/decision/action review, but it does not prove general autonomy or release a production Agent OS.

## 9. Final Recommendation

```text
DO NOT MERGE d46bd45.
DO NOT RELEASE.
Create a new c404e1e-based integration rehearsal and verify it before any merge decision.
```
