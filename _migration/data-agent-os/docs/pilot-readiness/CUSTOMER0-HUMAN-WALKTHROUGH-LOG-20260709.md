# Customer-0 Human Walkthrough Log

> Date: 2026-07-09  
> Operator: Agent (browser + API)  
> Local head: `1a38e44` (+ uncommitted CORS `:3001` allowlist fix)  
> Profile: **Default pilot** (flags OFF)  
> UI: `http://localhost:3001` (host `:3000` occupied by `multica-frontend`)  
> API: `http://localhost:8000`  
> Authorization: PR-33 Option A HOLD — no push

## Verdict

**Conditional PASS** for Customer-0 default-pilot loop after CORS fix.

- API Trusted Loop: **PASS**
- Browser Workspace / Report / Approvals / Outcomes / Knowledge: **PASS** (with notes)
- Blocker found and fixed locally: CORS rejected `http://localhost:3001`

## Artifacts (API smoke)

| Artifact | ID |
|----------|-----|
| trace_id | `trace-e4f67efcb871` |
| approval_id | `approval-20077dc2297e` |
| feedback_id | `feedback-c848318b6411` |
| evidence_chain_id | `evidence-22a295d9f85e` |
| knowledge_asset_id (candidate) | `knowledge-ee0af0b032c6` |

## Checklist results

| # | Surface | Result | Notes |
|---|---------|--------|-------|
| 1 | `/` GMV preset | **PASS** (after CORS fix) | First attempt Failed to fetch (CORS). After API rebuild: evidence + decision + action proposal. Preset “last week” returned **0 rows** (date window vs seed); smoke question with seed dates returned **1 row / GMV 128800**. |
| 2 | `/runs/{trace_id}` | **PASS** | Report loads: analysis, decision, evidence cards, execution trace (sql_safety → evidence → awaiting_approval → approved_operation_trace → outcome). |
| 3 | `/approvals/{id}` | **PASS** | Detail shows `approved`, proposal id, approver role, reason. |
| 4 | Approval execute | **PASS** (API) | Operator execute → `state=executed`. Browser Execute not re-run (already executed by smoke). |
| 5 | `/outcomes` | **PASS** | Form renders (Trace ID / Outcome / Reviewer). Outcome already recorded via API for smoke trace. |
| 6 | `/knowledge` | **PASS (empty OK)** | Catalog loads; `0 of 0` under default `active,published`. Candidate assets exist on run but are not catalog-listed until adoption/publish path. |
| 7 | Trace on report | **PASS** | Embedded Execution Trace shows full Trusted Loop + approval execution events. |
| 8 | Negative: run key on execute | **PASS** | `POST /approvals/.../execute` with `X-API-Key` → **401** `Invalid or missing operator key.` |
| 9 | `/workflows` flags off | **PASS** | **503** |
| 10 | Boundaries | **PASS** | HOLD unchanged; no R4/R5 auto-exec exercised. |

## Blocker found during walkthrough

### CORS origin missing for `FRONTEND_PORT=3001`

- Symptom: UI `Failed to fetch` from `http://localhost:3001`
- Preflight: `OPTIONS /runs` with `Origin: http://localhost:3001` → `400 Disallowed CORS origin`
- Cause: default allowlist only had `:3000` and Playwright `:3099`; host `:3000` is taken by `multica-frontend`, so compose UI binds `:3001`
- Fix (local, uncommitted): add `http://localhost:3001` / `http://127.0.0.1:3001` to `_cors_origins_from_env()` in `http_app.py` + unit test
- Verified: preflight 200 + Workspace GMV query succeeds

## Observations / follow-ups (not release blockers)

1. Workspace preset “GMV last week” uses relative dates → **0 rows** against current seed window; smoke/API with `2026-05-25..2026-06-01` returns data. Consider seed-aligned preset or UI date hint for Customer-0 demo.
2. Report page briefly shows skeleton then hydrates; OK after load.
3. Knowledge catalog empty until adoption/publish — expected for draft candidates; demo script should say so.
4. CORS fix + test are **uncommitted** under Option A HOLD (do not push unless Option B later).

## Commands used

```bash
colima start
FRONTEND_PORT=3001 docker compose up -d --build
./scripts/smoke-test.sh --no-start
# browser: http://localhost:3001
FRONTEND_PORT=3001 docker compose up -d --build api_server   # after CORS fix
```

## Related

- Checklist: `CUSTOMER0-HUMAN-WALKTHROUGH-CHECKLIST-20260709.md`
- M9 API log: `M9-OPERATOR-PILOT-LOG-20260708.md`
- PR-33 Option A HOLD
