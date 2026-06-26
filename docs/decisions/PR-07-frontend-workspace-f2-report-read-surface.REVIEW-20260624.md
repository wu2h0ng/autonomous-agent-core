# PR-07 Frontend Workspace F2 Report-Read Surface Review

- Date: 2026-06-24
- Branch: `codex/workspace-f2-api-report-surface`
- Base: `codex/workspace-f1-contract-surface` at `b4b451d`
- Initial implementation commit: `413a44a`
- Scope: review the static Frontend Workspace F2 read-only report projection from `GET /runs/{trace_id}/report`
- Status: reviewed and hardened locally; approved for explicit merge-order decision only; not merged, pushed, released, or deployed

## Findings

No write-surface blocker remains after this review pass. The implementation still calls only the report-read endpoint and does not call `/outcomes`, `/approvals`, `POST`, operator-key routes, or management surfaces.

Initial parallel review found several concrete concerns, all remediated:

- API key exfiltration risk through arbitrary `API base` input is closed by restricting report API origins to same-origin or localhost before the `X-API-Key` header is sent.
- Report-fed trace HTML injection risk is closed by replacing `traceSteps.innerHTML` with DOM node construction and `textContent`.
- Fallback mock SQL evidence no longer displays raw SQL, physical table names, or bound parameter names; it shows SQL safety summaries, fingerprints, and redacted parameters.
- HTTP error handling no longer displays raw response bodies; it shows a bounded status summary.
- `UserResultArtifact` mapping now follows the current FastAPI/Pydantic schema for dashboard widget `type` and decision `reason`.
- The layout now collapses before the 1280px notebook overflow band, and the API grid collapses to one column on mobile.
- README drift from F1 to F2 is closed.
- Inherited `git diff --check main..HEAD` EOF warnings in two reconcile docs are cleaned in this branch.

## Review Notes

- F2 is not a standalone branch against `main`. It is a stack-top branch: `codex/enterprise-integration-reconcile` -> `codex/workspace-f1-contract-surface` -> `codex/workspace-f2-api-report-surface`.
- Directly merging F2 into `main` would also bring the reconcile and F1 stacks. That can be acceptable only as an explicit combined-successor merge decision.
- The F2 UI remains a static prototype with one read-only API-backed surface. It is not production UI, not a React/Next.js scaffold, not an approval-execution UI, and not a full live golden-loop workspace.
- The test suite now guards visible report-read markers, no OS Core import boundary, no write/management endpoint calls, one `fetch(...)` call, no explicit `method:` override, no operator key, origin gating markers, text-node trace rendering, no raw SQL/error-body display, schema field mapping, and the responsive breakpoint.
- Python static tests are appropriate for this static prototype stage. A later production workspace should add browser-level contract tests with mocked `RunReportResponse` fixtures and network interception.

## Merge-Order Constraint

Recommended order:

```text
codex/enterprise-integration-reconcile
  -> codex/workspace-f1-contract-surface
  -> codex/workspace-f2-api-report-surface
```

Allowed next step: explicit founder/CTO merge-order decision in a clean integration worktree. If the decision is to merge F2 as the combined successor branch, call that out explicitly because it includes reconcile + F1.

Not allowed from this review: push, merge, deploy, external release, production UI claim, approval-execution UI claim, full live golden-loop workspace claim, full RBAC/DLP/tenant isolation claim, external-system exactly-once claim, external ACK confirmation claim, durable arbitrary external connector recovery claim, workflow replacement claim, autonomous-core adoption claim, or automatic R4/R5 execution claim.

## Verification

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest tests.unit.test_workspace_prototype -v
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
NODE_PATH=/Users/mima1234/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules /Users/mima1234/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node <playwright-static-server-check>
git diff --check
git diff --check main..HEAD
```

Observed results:

- Targeted workspace prototype tests: 10 tests OK.
- Full CI: 450 primary unittest/eval-discover tests OK, 4 skipped; 12 eval subset tests OK; ruff clean; format clean; OpenAPI contract up to date.
- Browser QA: desktop 1440px, notebook 1280px, and mobile 390px had no horizontal overflow; F2 report controls and report contract text were visible.
- Current working-tree `git diff --check`: clean.
- Stack diff `git diff --check main..HEAD`: clean after inherited EOF warning cleanup.

## Approval Status

Approved for explicit founder/CTO merge-order decision only. This review does not approve push, production release, external release, production frontend integration, React/Next.js scaffold, full RBAC/DLP, tenant isolation, field/row-level authorization, external-system exactly-once, external ACK confirmation, durable arbitrary external connector recovery, workflow replacement, autonomous-core adoption, or automatic R4/R5 execution.
