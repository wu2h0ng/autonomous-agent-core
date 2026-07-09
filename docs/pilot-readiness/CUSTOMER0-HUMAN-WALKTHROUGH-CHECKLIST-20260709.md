# Customer-0 Human Walkthrough Checklist

> Date: 2026-07-09  
> Repo: `ai-native-business-data-agent-os`  
> Local head: `1a38e44` (ahead of `origin/main@fed54d6` by 1 docs commit under PR-33 Option A HOLD)  
> Profile: **Default pilot** (staged-out flags OFF)  
> Authorization: `DEPLOYMENT_PUSH: HOLD` — no push, no RC tag, no external GA

## Purpose

Founder/operator **browser** rehearsal of the Trusted Business Loop against the local compose stack. This is the human follow-up to the automated M9 API walkthrough.

**Out of scope:** staging C/D/E flags, Customer-0 production data load, `origin/main` push, release tags.

## Preconditions

1. Colima/Docker running.
2. `.env` present (from `.env.example`); default keys OK for local-only pilot.
3. Stack up:

```bash
cd /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os
# If host :3000 is already taken (common), bind UI to 3001:
FRONTEND_PORT=3001 docker compose up -d --build
# UI:  http://localhost:3001
# API: http://localhost:8000/health
curl -s http://localhost:8000/health
```

**2026-07-09 session:** Colima started; postgres + api healthy on `:8000`; frontend on **`:3001`** because `:3000` was already bound.

Optional API warm-up (records IDs you can open in UI):

```bash
./scripts/pilot-walkthrough.sh
# Keep stack up (omit --down) if you want the same trace/approval in the browser.
```

## Auth keys (local default)

| Header / UI field | Value (from `.env`) | Used for |
|-------------------|---------------------|----------|
| `X-API-Key` / run key | `AGENT_OS_API_KEY` / `NEXT_PUBLIC_RUN_KEY` | `/runs`, `/knowledge`, outcomes |
| `X-Operator-Key` | `AGENT_OS_OPERATOR_API_KEY` | Approval **Execute** only |

Do not use the run key for approval execute.

## Checklist (mark Pass / Fail / N/A)

| # | Surface | Action | Expected | Result | Notes / IDs |
|---|---------|--------|----------|--------|-------------|
| 1 | `/` | Open workspace; run **GMV** preset (or NL question with dates) | Evidence cards + DataProduct/action proposal; no crash | ☐ | `trace_id=` |
| 2 | `/runs/{trace_id}` | Open run report from result link | Report projection + execution trace timeline visible | ☐ | |
| 3 | `/approvals` or `/approvals/{id}` | If awaiting approval, open detail | Shows proposal + risk; Execute requires operator key | ☐ | `approval_id=` |
| 4 | Approval Execute | Submit with **operator** key | State → executed (or clear refusal); no double-consume | ☐ | |
| 5 | `/outcomes` or FeedbackBar | Record outcome / feedback | Success ack; feedback id returned | ☐ | `feedback_id=` |
| 6 | `/knowledge` | Open catalog | Live API load (may be empty until adoption) | ☐ | |
| 7 | `/trace/{trace_id}` | Open trace (or report embedded trace) | Steps present; SQL Safety / Evidence path visible | ☐ | |
| 8 | Negative: wrong operator key | Attempt execute with run key / wrong key | 401/403; no execution | ☐ | |
| 9 | Negative: `/workflows` (default flags) | Hit workflows if exposed | **503** or unavailable with flags off | ☐ | |
| 10 | Boundaries | Confirm no R4/R5 auto-exec, no external claim | Proposal-only; HOLD unchanged | ☐ | |

## Pass criteria

- Steps 1–7 Pass (or 3–4 N/A only if run did not require approval — note why).
- Step 8 Pass (auth boundary).
- Step 9 Pass under default profile.
- No secrets committed; stack can be torn down with `docker compose down`.

## Record after walkthrough

Fill and keep under `docs/pilot-readiness/`:

```text
Operator: <name>
Date: 2026-07-09
Head: <git rev-parse HEAD>
Profile: default
trace_id:
approval_id:
feedback_id:
UI verdict: PASS | FAIL
Blockers:
Next: keep HOLD | request Option B | load Customer-0 data
```

Suggested filename: `CUSTOMER0-HUMAN-WALKTHROUGH-LOG-20260709.md`

## Teardown

```bash
docker compose down
# or: docker compose down --volumes   # wipes local postgres pilot data
```

## Related

- `docs/pilot-readiness/M8-PILOT-RUNBOOK.md`
- `docs/pilot-readiness/M9-OPERATOR-PILOT-LOG-20260708.md` (API automated)
- `docs/decisions/PR-33-deployment-push-authorization-20260709.md` (Option A HOLD)
