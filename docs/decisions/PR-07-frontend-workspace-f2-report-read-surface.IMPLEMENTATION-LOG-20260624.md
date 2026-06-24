# PR-07 Frontend Workspace F2 Report-Read Surface — Implementation Log

Date: 2026-06-24
Branch: `codex/workspace-f2-api-report-surface`
Base: `codex/workspace-f1-contract-surface`

## Scope

Add a read-only API-backed surface to the static workspace prototype so an operator can load an existing report projection from:

```text
GET /runs/{trace_id}/report
```

The surface consumes the public `RunReportResponse.user_result` / `UserResultArtifact` shape only. It maps report, dashboard, evidence-card, decision, business-action, redaction, trace, DataProduct-candidate, and KnowledgeAsset-candidate fields into the existing prototype panels.

## Boundaries

- No OS Core imports from workspace code.
- No `/outcomes`, `/approvals`, operator-key, approval-execute, or management endpoint calls.
- No new backend fields or API contract changes.
- Report API base is restricted to same-origin or localhost before sending `X-API-Key`.
- API/error/report fields rendered into trace and status surfaces use text nodes / bounded summaries, not HTML injection or raw error bodies.
- Mock SQL evidence follows the no-raw-SQL baseline: fingerprints and redacted parameters only.
- No production UI claim, no release, no push, no merge.
- R4/R5 remain proposal-only.

## Test-First Evidence

Added failing tests in `tests/unit/test_workspace_prototype.py` before implementation:

- `test_f2_reads_report_projection_through_public_api_contract`
- `test_f2_report_projection_is_read_only`
- `test_f2_report_projection_does_not_html_inject_trace_fields`
- `test_f2_report_projection_does_not_surface_raw_sql_or_error_body`
- `test_f2_responsive_layout_switches_before_1280px_overflow`

The RED run failed on the missing API controls / functions / contract markers. A later review-driven RED run also failed on the trace HTML-injection guard while `renderTrace()` still used `innerHTML`. GREEN runs passed after adding the report-read controls, mapping logic, origin guard, text-node trace rendering, no-raw-SQL mock evidence, bounded error summaries, and responsive layout hardening.

## Review Hardening

Parallel review found no write-surface blocker, but identified hardening items that are now closed:

- API key exfiltration risk through arbitrary `API base` input: closed by allowing only same-origin or localhost before the `X-API-Key` header is sent.
- Trace HTML injection risk after F2 introduced report-fed fields: closed by replacing `traceSteps.innerHTML` with DOM nodes and `textContent`.
- Raw SQL / bound parameter names in fallback mock evidence: closed by replacing query snippets with SQL safety summaries, fingerprints, and `parameters=redacted`.
- Error body leakage: closed by replacing raw `response.text()` display with bounded HTTP status summaries.
- Contract mapping drift: closed by reading `UserResultDashboardWidget.type` and `UserResultDecision.reason`, matching the FastAPI/Pydantic schema.
- 1280px notebook overflow risk and mobile API-grid squeeze: closed by moving the two-column breakpoint to `1320px` and collapsing `.api-grid` at the mobile breakpoint.
- Inherited `git diff --check main..HEAD` EOF warnings in two reconcile docs: closed by removing the extra EOF blank lines in this branch.

## Verification

- Targeted RED: `tests.unit.test_workspace_prototype` failed before implementation on missing F2 API controls/functions/contract markers.
- Targeted RED: `test_f2_report_projection_does_not_html_inject_trace_fields` failed while `renderTrace()` used `innerHTML`.
- Targeted GREEN: `tests.unit.test_workspace_prototype` passed after review hardening (`10 tests OK`).
- Full CI: `make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python` passed with `450 tests OK`, `4 skipped`, `12 eval tests OK`, ruff clean, format clean, and OpenAPI contract up to date.
- Browser QA: bundled Playwright static-server check passed at desktop 1440px, notebook 1280px, and mobile 390px with no horizontal overflow; screenshots written to `/tmp/workspace-f2-desktop-postreview.png`, `/tmp/workspace-f2-notebook-postreview.png`, and `/tmp/workspace-f2-mobile-postreview.png`.
