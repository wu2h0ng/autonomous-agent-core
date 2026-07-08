# M9 Operator Pilot Log

> Date: 2026-07-08  
> Operator: Agent (automated walkthrough + verification)  
> Head: `1f12d6923ed63d46b9ef92bb77a5970b64cf8e2b` (`origin/main`)  
> Verdict: **Default + staging walkthrough PASS** — `DEPLOYMENT_PUSH: HOLD` unchanged pending founder/CTO.

## Profiles exercised

| Profile | Command | Result |
|---------|---------|--------|
| Default pilot | `./scripts/pilot-walkthrough.sh --down` | **PASS** |
| Staging (C/D/E on) | `./scripts/pilot-walkthrough.sh --staging --down` | **PASS** |

## Default pilot run

**Chain:** health → POST `/runs` (approval-required GMV action) → operator execute → POST `/outcomes` → `/workflows` 503 (flags off)

| Artifact | ID |
|----------|-----|
| trace_id | `trace-4a5db21ec92c` |
| approval_id | `approval-0a158dcb1fb0` |
| feedback_id | `feedback-cf1a2b6fc39a` |

**Checks:**
- Approval reached `executed` state via `X-Operator-Key`
- Outcome recorded successfully
- Staged-out `/workflows` correctly **503** with default flags

## Staging pilot run

**Chain:** same governed loop + register workflow/MCP/policy → start workflow instance → verify `workflow.started` in RunTrace

| Artifact | ID |
|----------|-----|
| trace_id | `trace-4adf8da2d7d4` |
| approval_id | `approval-7e46f16f1e14` |
| feedback_id | `feedback-ad72ebb6a34e` |

**Checks:**
- `/workflows` and `/mcp/servers` reachable (not 503)
- Workflow instance started for trace-bound proposal
- **`workflow.started`** present in `GET /traces/trace-4adf8da2d7d4` events

## Operator UI surfaces (manual follow-up)

After `docker compose up -d`, operators should confirm in browser:

1. `/` — GMV preset → evidence cards + action proposal
2. `/runs/{trace_id}` — report + execution trace timeline
3. `/knowledge` — catalog loads (may be empty until adoption)
4. `/approvals/{approval_id}` — execute with operator key

Compose browser E2E: `./scripts/compose-e2e.sh` (verified in M8 @ same head family).

## CI / release gates (2026-07-08)

| Gate | Result | Notes |
|------|--------|-------|
| Default walkthrough | PASS | This log |
| Staging walkthrough | PASS | C/D/E trace chain |
| `make ci-local-full` | **PASS** | Format-check drift resolved at `e11ebadaf955bc51c1911acb1dc7b0236787af91` |
| `DEPLOYMENT_PUSH` | **AUTHORIZED** | PR-32 Option B authorized for candidate head `e11ebadaf955bc51c1911acb1dc7b0236787af91`; actual push remains a separate gate |

## Issues / risks

1. **Format-check drift** — blocks full `ci-local-full` until 3 files reformatted or excluded; does not affect walkthrough runtime behavior.
2. **RC branch lag** — `rc/phase-1-controlled-pilot-20260704` remains at historical head; `origin/main` at `1f12d69`. No RC tag created.
3. **External promotion** — M9 walkthrough success does not lift `DEPLOYMENT_PUSH: HOLD` without founder/CTO `AUTHORIZED` record.

## Recommended founder/CTO actions

| Option | Action |
|--------|--------|
| **A (default)** | Keep `DEPLOYMENT_PUSH: HOLD`; continue internal pilot with Customer-0 data |
| **B** | Authorize `DEPLOYMENT_PUSH: AUTHORIZED` + `candidate_head: 1f12d69…` after format-check fix + sign-off |
| **C** | Pin POC env to `git tag rc/phase-1-internal-pilot-20260708` (separate release gate; not created by this log) |

## Related records

- `docs/pilot-readiness/M8-PILOT-RUNBOOK.md`
- `docs/decisions/PR-31-m9-operator-walkthrough-verification-20260708.md`
- `docs/decisions/PR-32-deployment-push-decision-m9-20260708.md`

---

**Final sign-off:** M9 default + staging operator walkthrough verified; `make ci-local-full` green; PR-32 Option B/C authorized. Ready for founder/CTO-controlled push and local RC tag pinning; external GA remains gated.
