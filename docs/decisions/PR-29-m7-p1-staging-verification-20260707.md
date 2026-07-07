# PR-29: M7 P1 staging + live API E2E + C/D/E trace smoke

- Date: 2026-07-07
- Status: **Verified**

## Verified local head

Verified local head: `de99dea`

## Scope

1. Playwright live API closed-loop (mocked transport)
2. `docker-compose.staging.yml` + `.env.staging.example` (C/D/E flags on)
3. `scripts/smoke-test.sh` staged-out trace chain when `AGENT_OS_SMOKE_STAGED_OUT=true`
4. Alembic 0015/0016 tenant-scoped persistence alignment for compose postgres
5. SQLite `check_same_thread=False` + agent runtime tenant_id propagation for uvicorn
6. ADR-20260707 semantic graph slice acceptance record

## Commands

```bash
make ci PYTHON=.venv/bin/python
CI=1 npm run test:e2e  # apps/workspace/frontend — 7/7
./scripts/smoke-test.sh --down
make smoke-test-staging SMOKE_ARGS="--down"
```

## Result

- Playwright: **7/7** (4 shell + 3 api-loop mocked transport)
- Default compose smoke: **pass** (health → run → operator execute → outcome → /workflows 503)
- Staging smoke: **pass** with `workflow.started` on `/traces/{trace_id}` after C/D/E registration
- Migrations 0015 + 0016 applied on fresh postgres volume before api_server start
