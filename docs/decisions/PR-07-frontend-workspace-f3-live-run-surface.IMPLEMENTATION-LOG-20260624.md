# PR-07 Frontend Workspace F3a Live-Run Surface — Implementation Log

Date: 2026-06-24
Branch: `codex/workspace-f3-live-run-surface`
Base: `codex/workspace-f2-api-report-surface`

## Scope

Add a limited live-run surface to the static workspace prototype:

```text
POST /runs
```

The run button submits the current business question through the public
`RunRequest` contract and renders the returned `RunResponse.user_result` through
the existing F2 report panels.

## Boundaries

- No OS Core imports from workspace code.
- No `/outcomes`, `/approvals`, `/adoptions`, `/knowledge`, operator-key, approval-execute, or management endpoint calls.
- No backend schema changes and no invented response fields.
- `POST /runs` body is limited to `question`, empty `parameters`, and `audience`.
- API base is restricted to same-origin or localhost before sending `X-API-Key`.
- Error paths show bounded HTTP status summaries, not raw response bodies.
- R4/R5 remain proposal-only; business actions are rendered for review only.
- No production UI claim, no release, no push, no merge.

## Test-First Evidence

Added failing tests in `tests/unit/test_workspace_prototype.py` before
implementation:

- `test_f3_live_run_submit_uses_public_run_contract`
- `test_f3_live_run_submit_keeps_management_surfaces_blocked`
- `test_f3_live_run_submit_is_not_nested_inside_report_loader`

The RED run failed on the missing F3a contract markers, missing `POST /runs`
submit path, missing second `fetch(...)`, and missing global `submitGovernedRun`
handler. The first GREEN pass exposed a real script-structure bug: the submit
handler had been inserted inside `loadReportProjection`, so it would not be
browser-callable. The scope test now guards that failure mode.

## Verification

Targeted workspace prototype tests:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python \
  -m unittest tests.unit.test_workspace_prototype -v
```

Observed target result:

- `13 tests OK`

Full branch verification:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Observed full result:

- `453 tests OK`, `4 skipped`
- `12 eval tests OK`
- ruff clean
- format clean
- OpenAPI contract up to date

Browser QA:

- In-app Browser attempted to load `http://127.0.0.1:8123/`, but the app
  runtime redirected the tab to a policy-blocked crash page after the local
  request reached the static server. This was treated as a tool boundary, not
  page success.
- Fallback Playwright QA against the same static server loaded the page,
  confirmed the F3a boundary and `POST /runs` surface, clicked the live-run
  button with no API server running, and observed the bounded `network` state.
- Desktop viewport `1440x900`: `scrollWidth=1440`, `clientWidth=1440`.
- Mobile viewport `390x900`: `scrollWidth=390`, `clientWidth=390`,
  `overflow=false`.
- The only browser console error was the expected
  `net::ERR_CONNECTION_REFUSED` for the absent local API server.
- Screenshots: `/tmp/workspace-f3a-desktop.png`,
  `/tmp/workspace-f3a-mobile.png`.

## Non-Claims

This is not production UI, not a React/Next.js scaffold, not a full live
golden-loop workspace, not approval-execution UI, not external release, not full
RBAC/DLP/tenant isolation, not external-system exactly-once, not external ACK
confirmation, not durable arbitrary external connector recovery, and not
automatic R4/R5 execution.
