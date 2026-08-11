# M8 Internal Pilot Runbook

> Date: 2026-07-08  
> Repo: `ai-native-business-data-agent-os`  
> Head: `origin/main@0ffe523` (M7 complete)  
> Verdict: **Internal pilot ready** under `DEPLOYMENT_PUSH: HOLD` — no external GA claim.

## Purpose

Run a **controlled internal POC** of the Trusted Business Loop with optional staging verification of staged-out capabilities (C/D/E). Default pilot keeps all staged-out flags **off**.

## Profiles

| Profile | Env file | Compose | Staged-out flags | Use when |
|---------|----------|---------|------------------|----------|
| **Default pilot** | `.env` (from `.env.example`) | `docker-compose.yml` | OFF | Trusted Loop + approval + outcome |
| **Staging pilot** | `.env.staging` (from `.env.staging.example`) | `+ docker-compose.staging.yml` | ON (C/D/E) | Verify workflow/MCP/policy trace chain |

## Required configuration

```bash
cp .env.example .env
# Production pilot MUST set:
#   AGENT_OS_STORE_BACKEND=postgres  (via compose — automatic)
#   AGENT_OS_EXECUTOR=sqlite         (or real provider)
#   Rotate AGENT_OS_*_API_KEY values
```

| Variable | Default pilot | Notes |
|----------|---------------|-------|
| `AGENT_OS_API_KEY` | `dev-internal-key` | `X-API-Key` for `/runs`, `/knowledge`, etc. |
| `AGENT_OS_OPERATOR_API_KEY` | `dev-operator-key` | `X-Operator-Key` for `/approvals/{id}/execute` only |
| `AGENT_OS_EXECUTOR` | `sqlite` | `static` = demo fixtures only |
| `NEXT_PUBLIC_RUN_KEY` | same as internal key | Frontend workspace auth |

## Feature flag matrix (default-off)

| Flag | Env var | Default | Staging |
|------|---------|---------|---------|
| MCP Gateway | `AGENT_OS_MCP_GATEWAY` | `false` | `true` |
| Full BPM | `AGENT_OS_FULL_BPM_WORKFLOW` | `false` | `true` |
| R4/R5 auto-exec | `AGENT_OS_R4_R5_AUTO_EXECUTION` | `false` | `true` |

**Never enable staging flags on production without founder/CTO authorization and ADR-0012 preconditions.**

## Quick start

### 1. API smoke (CLI)

```bash
./scripts/smoke-test.sh --down
# Staging C/D/E trace chain:
make smoke-test-staging SMOKE_ARGS="--down"
```

### 2. Full stack (UI + API)

```bash
docker compose up -d --build
# UI:  http://localhost:3000
# API: http://localhost:8000/docs
```

### 3. M8 walkthrough script

```bash
./scripts/pilot-walkthrough.sh --down          # default profile
./scripts/pilot-walkthrough.sh --staging --down # staging profile
```

### 4. Browser E2E against live compose API

```bash
./scripts/compose-e2e.sh --down
# Or: make compose-e2e COMPOSE_E2E_ARGS="--down"
```

## Operator loop (human pilot)

1. **Query** — Workspace `/` → GMV preset or NL question → evidence + action proposal.
2. **Report** — `/runs/{trace_id}` → report projection + execution trace timeline.
3. **Approval** — If `awaiting_approval`, `/approvals/{id}` → Execute with operator key.
4. **Outcome** — `/outcomes` or FeedbackBar → record feedback.
5. **Knowledge** — `/knowledge` → catalog (live API); assets appear after adoption paths.
6. **Trace** — `/trace/{trace_id}` or report page → verify `workflow.started` (staging only).

## C7 pause (corrigibility)

When the pause shell is active, governed execution paths refuse before side effects. Operators must:

1. Confirm pause state via runtime/admin surface (if exposed).
2. Do **not** bypass with direct connector calls.
3. Resume only through authorized operator procedures documented in ADR-0003 / P5.2a.

## Rollback

| Layer | Action |
|-------|--------|
| Compose stack | `docker compose down --volumes` |
| Approval action | Use connector rollback via action_record ledger (operator execute path) |
| Database | Restore postgres volume snapshot; re-run `scripts/migrate.sh` |
| Release | `DEPLOYMENT_PUSH: HOLD` — no tag push required for pilot teardown |

## Verification gates (before claiming pilot success)

```bash
make ci PYTHON=.venv/bin/python
AGENT_OS_DATABASE_URL=postgresql+psycopg://... make ci-local-full PYTHON=.venv/bin/python
make controlled-pilot-readiness-check PYTHON=.venv/bin/python  # expect HOLD OK
make push-authorization-check PYTHON=.venv/bin/python         # expect exit 2 under HOLD
```

## Boundaries (unchanged)

- R4/R5 **proposal-only** by default; auto-exec only with flag + policy + ADR-0012.
- No external GA / release tag without founder/CTO `DEPLOYMENT_PUSH` authorization.
- OS Core does not import domain packs; SQL Safety and EvidenceChain are mandatory for formal answers.

## Related records

- `docs/decisions/PR-29-m7-p1-staging-verification-20260707.md`
- `docs/decisions/PR-30-m8-pilot-execution-20260708.md`
- `docs/pilot-readiness/M6-PILOT-READINESS-REPORT-2026-07-06.md`
- `docs/architecture_reviews/AR-20260707-staged-out-capabilities-cde.md`
