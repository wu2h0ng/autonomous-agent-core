# PR-07 Frontend Workspace F3 Integration Rehearsal — Verification

Date: 2026-06-24
Branch: `codex/workspace-f3-integration-rehearsal`
Base: local `main` at `fb2399a`

## Scope

This branch is a merge-order rehearsal only. It mechanically applies the
product-integration stack:

```text
main
  -> codex/enterprise-integration-reconcile
  -> codex/workspace-f1-contract-surface
  -> codex/workspace-f2-api-report-surface
  -> codex/workspace-f3-live-run-surface
```

It does not merge to `main`, push, release, deploy, or approve production UI.

## Merge Result

- `main -> codex/enterprise-integration-reconcile`: content conflicts in
  `README.md` and `docs/CURRENT_STATE.yaml`; resolved in this rehearsal by
  preserving the reconcile branch's product-integration status anchor before
  continuing the stack.
- `reconcile -> F1`: merged without conflicts.
- `F1 -> F2`: merged without conflicts.
- `F2 -> F3a`: merged without conflicts.

## Verification

Baseline before stack merge:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Observed baseline result:

- `435 tests OK`, `4 skipped`
- `12 eval tests OK`
- ruff clean
- format clean
- OpenAPI contract up to date

Final stack verification:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Observed final result:

- `453 tests OK`, `4 skipped`
- `12 eval tests OK`
- ruff clean
- format clean
- OpenAPI contract up to date

Browser QA:

- Static server: `python3 -m http.server 8123 --bind 127.0.0.1`
- Playwright loaded `http://127.0.0.1:8123/` at `1440x900` and `390x900`.
- F3a boundary and `POST /runs` markers were visible.
- Clicking the live-run button with no API server entered the bounded
  `network` state and displayed `Run request failed.`
- Desktop viewport: `scrollWidth=1440`, `clientWidth=1440`.
- Mobile viewport: `scrollWidth=390`, `clientWidth=390`, `overflow=false`.
- The only browser console error was the expected local API connection refusal.
- Screenshots: `/tmp/workspace-f3-rehearsal-desktop.png`,
  `/tmp/workspace-f3-rehearsal-mobile.png`.

## Non-Claims

This is not production UI, not a full live golden-loop workspace, not
approval-execution UI, not a React/Next.js scaffold, not external release, not
external-system exactly-once, not external ACK confirmation, not durable
arbitrary external connector recovery, and not automatic R4/R5 execution.

Founder/CTO merge and push decisions remain explicit gates.
