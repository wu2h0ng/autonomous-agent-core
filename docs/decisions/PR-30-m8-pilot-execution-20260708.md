# PR-30: M8 internal pilot execution — live UI + compose E2E + runbook

- Date: 2026-07-08
- Status: **Verified**
- Parent: M7 @ `0ffe523`

## Verified local head

Verified local head: `0ffe523` (M8 changes on working tree — bind after commit)

## Scope

1. `docs/CURRENT_STATE.yaml` — M8 immediate_next + status refresh
2. `docs/pilot-readiness/M8-PILOT-RUNBOOK.md` — flag matrix, profiles, operator loop
3. Runs/Report/Knowledge live UI — trace on run report, trace lookup, CORS for browser API
4. `scripts/compose-e2e.sh` + `e2e/workspace.compose-api.spec.ts` — Playwright vs compose API
5. `scripts/pilot-walkthrough.sh` — default + `--staging` rehearsal entry points

## Commands

```bash
make ci PYTHON=.venv/bin/python
CI=1 npm run test:e2e  # apps/workspace/frontend — 7 passed, 3 compose skipped
./scripts/compose-e2e.sh
./scripts/pilot-walkthrough.sh --down
make pilot-walkthrough-staging PILOT_ARGS="--down"  # optional C/D/E profile
PYTHONPATH=... .venv/bin/python -m unittest tests.unit.test_http_app.CorsMiddlewareTest -v
```

## Result

- Playwright mock loop: **7/7** pass; compose spec **3/3** pass when `COMPOSE_E2E=1` via `compose-e2e.sh`
- CORS preflight: **pass** (`CorsMiddlewareTest`)
- Pilot walkthrough default: **pass** (smoke-test chain)
- Boundaries: `DEPLOYMENT_PUSH: HOLD`; staged-out flags default-off; R4/R5 proposal-only unchanged

## Entry points

| Surface | Path |
|---------|------|
| Run report + trace | `/runs/{trace_id}` → `getReport` + `getTrace` |
| Knowledge catalog | `/knowledge` → `getKnowledgeAssets` |
| Compose E2E | `./scripts/compose-e2e.sh` |
| Walkthrough | `./scripts/pilot-walkthrough.sh [--staging] [--down]` |

## OpenAPI

- CORS middleware only; no route/schema delta — OpenAPI snapshot unchanged.
