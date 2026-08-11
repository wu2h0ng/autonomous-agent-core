# Codex Task Packet — ADR-0002 branch remediation (H1 / M2 / M1)

> Self-contained handoff for the Codex runner. Target repo `ai-native-business-data-agent-os`, branch `codex/durable-action-ledger` (already checked out). Author: Claude (CTO/spec). Source of findings: [REVIEW-20260624](ADR-0002-governed-action-outcome-loop-v0.REVIEW-20260624.md); governance: [AR-20260624](../architecture_reviews/AR-20260624-http-principal-scope-and-redaction.md). Founder rulings recorded 2026-06-24.

## Brief

Three review findings gate the merge of this branch. Remediate all three. **TEST-FIRST** (red test → implementation → green), minimal scoped changes, do not overwrite unrelated work. Run `make ci`; for persistence/auth tasks also run the postgres-backed `make ci-local-full` (`AGENT_OS_DATABASE_URL` disposable). **Do not merge/push/release — founder gate retained.**

Guardrails: no `os_core` import of `examples/`/`domain_packs/`/`providers/`/`action_connectors/`; no R4/R5 auto-execution; claim boundary stays P5-only (no autonomy/G-Eco). Do not commit secrets. If requirements are unclear, route back to Claude, do not guess.

## Spec

### TASK H1 — HIGH, concurrency bug (stale-claim reclaim TOCTOU)
- **Where:** `packages/persistence/src/agent_os_persistence/repositories.py:444-452` (reclaim CAS), `:435-442`.
- **Bug:** the reclaim `UPDATE` is `WHERE status=="executing" SET status="executing"` — both sides equal, so the compare-and-swap discriminator never flips. Two concurrent cross-process reclaimers of the same stale claim both get `rowcount==1` and both enter `execute_approved_operation` → **double connector execute**. Per-process `threading.RLock` does not protect this (reclaim exists for the cross-process/crash case).
- **Fix (pick one, keep the pending→executing CAS untouched):**
  1. *Preferred:* gate the reclaim `UPDATE` on the **exact observed prior claim token** — add a WHERE on `_claim.claimed_at` (or introduce a claim nonce) so only the racer that observed that token wins.
  2. two-phase `executing→reclaiming→executing` (discriminator flips on step 1).
  3. `SELECT … FOR UPDATE` on the row inside `claim()` to serialize readers (pattern already at `repositories.py:156`).
- **Acceptance:** a NEW test drives two concurrent reclaimers of the same stale claim and asserts **exactly one wins / exactly one execute**. It must FAIL on current code and PASS after the fix. Existing `claim`/`release`/double-consume tests stay green.

### TASK M2 — MEDIUM, test gap (operator-key 503-unconfigured)
- **Where:** `apps/api_server/src/agent_os_api/http_app.py:578-593` (503 at `:581-589`); test file `tests/unit/test_http_app.py`.
- **Add:** `test_unconfigured_operator_key_returns_503` — `_make_client(API_KEY, operator_api_key=None)` then `POST /approvals/{id}/execute` with any `X-Operator-Key` asserts **503**. Must fail if that branch regresses to 401/accept.

### TASK M1 — founder-ruled audience-first redaction
Refactor so the **primary** redaction gate is audience/projection; `data_classification` becomes a **secondary strength knob**. Chain: `principal/scope → audience ceiling → audience projection → data_classification (strength)`. Current gate to replace: `applied = audience == 'external' and data_classification != 'public'` (`apps/api_server/src/agent_os_api/outcome_service.py:121`).

**Frozen rules (implement exactly):**
1. `audience=internal`: keep internal result detail, but NEVER leak raw SQL text or raw parameter **values**.
2. `audience=external` + `data_classification != 'public'`: redact physical sources, metric dimensions, SQL metadata, columns, preview rows, chart x/y fields, KPI values; **preserve** `row_count` + explicit redaction metadata.
3. `audience=external` + `data_classification == 'public'`: MAY show public metric **data** detail (columns / preview / KPI / dimensions) + metric identity, but STILL strip raw SQL, raw param values, **and** physical schema/table names, bound parameter **names**, and the SQL fingerprint (CTO reading of the "no raw SQL" baseline — these are infrastructure, not public data). *Founder may relax this at verification.*
4. `external_report` principal ALWAYS resolves to `audience=external` even if the body says `internal` (keep `http_app.py:612`).
5. Keep `audience` a 2-way `internal|external` for M1. Do **not** add `audience_profile` (customer/partner/investor/auditor/public) — deferred to M2.

- **Re-point the enshrining test:** `tests/unit/test_outcome_service.py:266` (`test_external_audience_keeps_public_metric_details`) must now assert a public metric under external **still hides** `checked_tables`/`checked_schemas`/`bound_parameter_names`/`sql_fingerprint`, while it MAY show `columns`/`preview`/KPI.
- **Document** (code docstring + `docs/CURRENT_STATE.yaml`): this is NOT full RBAC / DLP / tenant isolation / field-or-row-level authorization.

## Plan (suggested order)
1. M2 first (cheapest, isolated): red test → confirm 503 path covered.
2. H1: red two-reclaimer race test → implement CAS discriminator fix → green; re-run persistence suite + `make ci-local-full`.
3. M1: re-point `test_external_audience_keeps_public_metric_details` + add a public-external infra-redaction assertion (red) → refactor `_redaction_summary`/projection so audience is the primary gate and classification the strength knob → green.
4. Full `make ci` + `make ci-local-full`.

## Verification (record results in verification.md)
```
make ci PYTHON=.venv/bin/python
export AGENT_OS_DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/agent_os_test"
make ci-local-full
# targeted:
python -m unittest tests.unit.test_http_app tests.unit.test_outcome_service tests.unit.test_factory_postgres_store tests.unit.test_persistence -v
```
Expected: H1 race test + M2 503 test + re-pointed M1 test all green; no regression; OpenAPI drift clean.

## Deliverables back to Claude
`implementation-log.md` (files changed, commands) + `verification.md` (commands + results). Claude runs `claude-diff-review` on the output before the founder's merge gate.
