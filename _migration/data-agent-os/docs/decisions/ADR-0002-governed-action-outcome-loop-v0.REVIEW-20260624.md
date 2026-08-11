# Claude Diff Review — `codex/durable-action-ledger` vs `main`

- Date: 2026-06-24
- Reviewer: Claude (CTO / adjudication role)
- Subject: ADR-0002 governed-action outcome loop — durable action ledger + auth/redaction/report surface
- Branch: `codex/durable-action-ledger` (merge-base `26d42d1`); 22 files, +2247/-96
- Method: 5-lens adversarial workflow (20 agents); **every finding independently re-derived at file:line, default-refuted-if-unconfirmed**. 4 candidate findings were refuted on verification (listed below).
- Parent: [ADR-0002](ADR-0002-governed-action-outcome-loop-v0.md); related governance AR: [AR-20260624-http-principal-scope-and-redaction](../architecture_reviews/AR-20260624-http-principal-scope-and-redaction.md)

## Approval Status

**CONDITIONAL — DO NOT MERGE** until the three merge-blockers (M1–M3) are resolved. The core governed-action mechanism is sound and well-tested; the blockers are one real concurrency bug + the missing architecture-review trail for the auth/redaction surface + one founder design decision.

---

## Findings (by severity)

### 🔴 HIGH

**H1 — Stale-claim reclaim TOCTOU: two cross-process reclaimers both win → double connector execute.** `repositories.py:444-452` (reclaim CAS), `:435-442`.
The reclaim `UPDATE` is `WHERE status=="executing" SET status="executing"` — both sides equal, so the compare-and-swap discriminator never flips. Two runtime instances that both observe the same stale `executing` claim both pass `_is_stale_claim`, both issue the no-op-transition UPDATE, and **both get `rowcount==1`** (empirically reproduced on two connections), then both enter `execute_approved_operation` → double connector execute. Masked for `ActionRecordConnector` only by its deterministic `idempotency_key` (2nd degrades to `idempotent_replay`); any connector without that map, or a real external system, double-executes. The per-process `threading.RLock` (`trusted_loop.py:213/665`) does not protect this — durable reclaim exists precisely for the cross-process/crash case.
*Fix:* make the reclaim CAS carry a changing discriminator — (a) gate the UPDATE on the prior `_claim.claimed_at` token; or (b) two-phase `executing→reclaiming→executing`; or (c) `SELECT … FOR UPDATE` on the row in `claim()` (already the pattern in `SqlKnowledgeStore.get_by_trace`, `repositories.py:156`).

**H2 — New auth/permissions model landed with no ADR/AR (governance).** `http_app.py:43,48-54,57-61,67-90,92`.
`ApiPrincipal` + 7 `API_SCOPE_*` + internal/external_report/operator principals + `authorize_principal_scope` (403) + the `AGENT_OS_EXTERNAL_API_KEY` second key class are all net-new vs main (`main:http_app.py` has 0 `ApiPrincipal` refs). `git diff main...HEAD -- docs/` touches **only** `CURRENT_STATE.yaml` — no ADR/AR. Enterprise `CLAUDE.md` mandates an ADR/AR before changing *auth, permissions, public APIs, Approval behavior*. The mechanism itself reviewed **sound** (see Verified-Sound); the defect is the **bypassed mandatory gate**, not a demonstrated privilege bug. *Fix:* record it — see AR-20260624 (deliverable A) + CTO gate before merge.

**H3 — Public OpenAPI contract changed with no AR (governance).** `apps/api_server/openapi.json` (X-Operator-Key `required:false→true`; `audience` enum; 3 net-new evidence-card schemas), injected via `http_app.py:141-164` runtime monkeypatch of `app.openapi`. `CLAUDE.md` requires an ADR/AR for *contracts/schemas/public-API/compatibility* changes; governing `AR-20260611-api-contract-openapi-stabilization` was not updated. *Fix:* fold into AR-20260624 (or extend AR-20260611); note the deliberate advertise-required/enforce-401 divergence.

### 🟠 MEDIUM

**M1 — External read-side redaction is gated on metric `data_classification`, not principal/audience.** `outcome_service.py:121` (`applied = audience == "external" and data_classification != "public"`), consumed at `:140,:178-182,:193-194,:221-223`; enshrined by `tests/unit/test_outcome_service.py:266`.
A metric labelled `data_classification="public"` defeats the entire external wall for **every** external-report key holder: physical tables, **bound parameter names** (the fixture literally exposes one named `secret_token`), SQL fingerprint, columns, and **preview rows (real data values)** all reach the external response. Two lenses disagreed (auth: low/by-design; redaction: high). **Adjudicated MEDIUM**: not exploitable with the shipped pack (default classification is `internal`), but a latent footgun — labelling a metric "public" silently drops the wall, and a test currently locks the leak in as "correct."
*Decision required (founder/CTO):* decouple redaction from classification — `applied = audience == "external"` — and, if a public fast-path is wanted, keep stripping source/SQL metadata (tables/schemas/param-names/fingerprint) and only relax column/preview values. Update `test_external_audience_keeps_public_metric_details` accordingly.

**M2 — Operator-key `503`-unconfigured branch is untested.** `http_app.py:578-593` (raises 503 at `:581-589`); `tests/unit/test_http_app.py` only covers the **internal** channel's 503 (`_make_client` always sets an operator key). The operator channel gates R4-adjacent governed execution; a refactor flipping unconfigured→401-or-accept would go unnoticed. *Fix:* `test_unconfigured_operator_key_returns_503` — `_make_client(API_KEY, operator_api_key=None)` then `POST /approvals/{id}/execute` asserts 503.

### 🟡 LOW / NIT

- **L1** `connector.py:127-130` — in-memory `ActionRecordStore.restore` ignores `rollback_operation_id` and full-replaces, diverging from the SQL store's scoped restore (would drop unrelated newer records). In practice single-op-in-flight, so low; align or document.
- **L2** `http_app.py:104-122` — distinctness validator compares byte-exact and treats a whitespace-only key as configured; strip before truthiness/distinctness checks.
- **L3** `outcome_service.py:150-156` — metric_contract card keeps `metric_name/owner/display_name/unit` under redaction (by-design; mild org-structure disclosure). Add to redacted set only if undesired.
- **L4** `http_app.py:134-138` — external blocked-run projection drops `trace_id/details` (correct) but passes `block.message/stage/code`; add a test asserting `message` never embeds schema/table/SQL.
- **L5** scope-ledger — durable action_record ledger + approval-context resume are **defensible-hardening** of ADR-0002 D3/D5 but warrant a one-line AR note (SPEC §L225 deferred durable storage to "a future ADR").
- **N1** `0007_action_records.py:30-31` / `schema.py:60` — redundant explicit index on `idempotency_key` (UNIQUE already backs an index); drop it.
- **N2** `http_app.py:590-593` — always-true operator scope check (defense-in-depth against a frozen constant); harmless.

---

## Refuted candidate findings (verification killed these — do not re-raise)

- **"idempotency-after-rollback: SQL store silently double-inserts / backends diverge"** → REFUTED. Both backends agree in every ordering; the finding mis-read the SQL scoped delete (`repositories.py:326-331` preserves snapshot records). Residual: a minor coverage gap only.
- **"governed-loop resume refusals untested"** → REFUTED. `test_outcome_service.py` has two negative resume tests (rejected-stays-rejected; no-pending-context raises).
- **"OpenAPI required-flip has no regression test"** → REFUTED. `test_openapi_contract.py:58-88` + snapshot-diff cover it.
- **External-projection alternate leaks (top-level fields / dashboard widget / default-audience fail-open)** → REFUTED; all collapse into M1 (the classification gate) — widget paths are airtight for non-public metrics.

## Verified sound (affirmative coverage — no fix needed)

- **Auth mechanism:** constant-time compare (`secrets.compare_digest`), fail-closed 503, per-route scope checks on every endpoint, operator/run channel separation (run keys → 401, never reach operator branch), external key hard-pinned to external projection + barred from management surfaces, distinct-key validation at `create_app`.
- **Governed-loop core:** `execute_approved_operation` refuses non-approved / proposal-mismatch / operation-mismatch / fingerprint-mismatch(operation+params+evidence) / missing-approval-required / R4-R5, re-asserts `_assert_grounded` at `:762` **and** again inside `_execute_governed_operation:943` immediately before `connector.execute:1020`; resume binds the stored `ApprovalOperationContext`, not client input. **No new R4/R5 auto-exec path.**
- **Idempotency:** replay returns first record (no new row); conflict (same key/different payload) raises loudly and audits a **fingerprint only** (no raw payload leak).
- **SQL rollback:** scoped delete preserves the snapshot record **and** unrelated newer records.
- **Pending-path claim CAS:** discriminator flips correctly; double-consume blocked.
- **Migration 0007:** linear chain, correct nullability/uniqueness, correct `downgrade()`.
- **Redaction (non-public metrics):** airtight — KPI/columns/preview/chart x-y blanked, trend widget suppressed, schemas/tables/param-names/fingerprint stripped; tests assert the rendered JSON contains no `sales.orders`/`order_date`/`sha256:`/date leakage.
- **Boundary:** `os_core` imports nothing from `examples/`/`domain_packs/`/`providers/`/`action_connectors/` — CLEAN.

## Open questions

1. M1 redaction policy: decouple from classification (recommended), or accept+document public-exposes-internals?
2. Should the durable surface (ledger + approval-context resume) be a defensible-hardening note under ADR-0002, or carved into its own ADR? (Review recommends: note under AR-20260624.)

## Required changes before merge

1. **H1** — fix the stale-claim reclaim CAS (concurrency bug). Add a two-reclaimer race test.
2. **H2 + H3** — land AR-20260624 (auth/redaction/principal-scope/external-key/OpenAPI) + CTO gate; reference it from `CURRENT_STATE.yaml` instead of folding under ADR-0002.
3. **M1** — founder/CTO decision on the redaction gate; implement + re-point the enshrining test.
4. **M2** — add the operator-503 test.
5. L1–L5/N1–N2 — optional, can be a follow-up; L1 and L2 recommended.
