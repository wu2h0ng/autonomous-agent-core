# AR-20260624: HTTP Principal/Scope Auth + Audience Redaction + External-Report Key

- Status: **Accepted** (retro-active registration accepted at CTO/founder gate on 2026-06-24; merge of `codex/durable-action-ledger` authorized)
- Scope: the auth/authz + read-side redaction + external-report key + public-OpenAPI surface that landed on branch `codex/durable-action-ledger` **under ADR-0002 without its own architecture review**
- Risk class: **R3** (auth/permissions + data egress / DLP-adjacent + public-API contract)
- Parent: [ADR-0002 governed-action outcome loop](../decisions/ADR-0002-governed-action-outcome-loop-v0.md); findings: [REVIEW-20260624](../decisions/ADR-0002-governed-action-outcome-loop-v0.REVIEW-20260624.md)
- Boundary: registers a **deployment-layer** product surface; no `os_core` change, no autonomy claim. Claim line unchanged — P5 governance + governed action, **not** G-Eco autonomy.

## 1. Context

ADR-0002 v0 scoped exactly **one** new auth channel — the operator key for approval execution (§2 D5) — and explicitly fenced breadth into D7. The `codex/durable-action-ledger` branch additionally introduced a **complete authorization model and a read-side data-egress control** that were never reviewed:

- a principal/scope authorization layer applied to all protected routes;
- a **second API-key class** (external-report key) with an audience ceiling;
- audience-aware **redaction** of user-facing results (a DLP-adjacent egress control);
- **public OpenAPI** contract changes (operator-key `required` flip, `audience` enum, evidence-card schemas).

Enterprise `CLAUDE.md` → *Changes Requiring Architecture Review* mandates an ADR/AR before changing **auth, permissions, secrets, public APIs, compatibility, Approval, EvidenceChain, or data egress**. All of the above engages that rule and shipped with the delta recorded only in `CURRENT_STATE.yaml` (a status tracker, not a review). This AR closes that gap and gates merge.

The mechanism reviewed **structurally sound** (see [REVIEW-20260624](../decisions/ADR-0002-governed-action-outcome-loop-v0.REVIEW-20260624.md) → Verified-sound). This AR is about the **decision trail and one design ruling**, not a rewrite.

## 2. Surface inventory and classification

**Defensible-hardening of the ADR-0002 loop** (accept under ADR-0002 with this AR note):
| Surface | Rationale |
|---|---|
| Durable connector-side `action_record` ledger (`SqlActionRecordStore`, alembic `0007`, replay/conflict audit) | Backs ADR-0002 D3 idempotency + D5 durable e2e; SPEC §L225 deferred durable storage to a future ADR — this AR is that note |
| Durable approval-context resume + stale-claim lease recovery | Hardening of the D5 approval-resume mechanism (cross-runtime, crash-recovery) |

**Net-new surfaces requiring this review (were `needs-own-adr`):**
| Surface | Entry point |
|---|---|
| `ApiPrincipal` + 7 `API_SCOPE_*` + `authorize_principal_scope` (403) authorization model | `http_app.py:48-92` |
| External-report API key class (`AGENT_OS_EXTERNAL_API_KEY`), audience-ceiling, projection-only cap | `http_app.py:43,67-90,605-616` |
| Audience-aware read-side redaction of `user_result` (DLP-adjacent egress) | `outcome_service.py:108-180,199-350`; `_external_run_response_projection`/`_external_block_projection` `http_app.py:125-138` |
| User-facing report/evidence-card/chart-dashboard artifact (predates branch on `main` `933e47e`; chart/cards/redaction increments are new) | `outcome_service.py` `_build_user_result_artifact`, `_report_evidence_cards`, `_chart_fields` |
| Public OpenAPI changes (X-Operator-Key `required:true`, `audience` enum, 3 evidence-card schemas) | `apps/api_server/openapi.json`; runtime patch `http_app.py:141-164` |

## 3. Entry Points

- `POST /runs` — principal/scope gated (`require_api_scope`); `audience` forced to `external` for the external-report principal (`http_app.py:612`); returns redacted `user_result` via `_external_run_response_projection`.
- `POST /approvals/{approval_id}/execute` — operator-key only (`require_operator_api_key`, `http_app.py:696`); 401 (not 422) on missing/wrong key.
- `POST /outcomes`, `POST /adoptions`, `GET /knowledge/search`, `GET /traces` — internal-scope gated; external-report key correctly 403s (lacks scope).
- Auth wiring: `authenticate_api_key` (401/503), `_validate_distinct_configured_keys` (create_app), `_key_matches` (constant-time).

## 4. Required decision (founder/CTO) — redaction gate

**M1 (REVIEW-20260624):** read-side redaction is gated on `metric.data_classification != "public"` (`outcome_service.py:121`), **not** on the principal/audience. A metric labelled `public` defeats the external wall for every external-report key holder — leaking physical tables, **bound parameter names** (fixture exposes one named `secret_token`), SQL fingerprint, columns, and **preview rows (real values)** — and `test_outcome_service.py:266` currently locks this in as intended.

- **Recommended ruling:** decouple — `applied = audience == "external"`; if a public fast-path is desired, still strip source/SQL metadata and only relax column/preview values; re-point the enshrining test.
- **Alternative:** explicitly accept and document that `public` classification intentionally exposes internals to external keys (and accept the footgun).

Default classification is `internal`, so this is **not exploitable with the shipped pack** — but it is a latent egress footgun and must be ruled on, not shipped silently.

## 5. Tests

- Present & discriminating: scope 403s (external-report on /outcomes,/adoptions,/knowledge/search,/traces), key distinctness (ValueError), operator-vs-run rejection (401 both ways), OpenAPI operator-key-required, non-public redaction (positive leak assertions on rendered JSON), external block/run projections.
- **Gap (M2):** operator-key **503-unconfigured** path untested (only internal channel's 503 covered). Add `test_unconfigured_operator_key_returns_503`.
- Optional: assert `block.message` never embeds schema/SQL for external (L4); whitespace-key distinctness (L2).

## 6. Gate Result

Accepted for merge on 2026-06-24 under the standing boundaries in §7:

1. **This AR accepted at CTO/founder gate** and referenced from `CURRENT_STATE.yaml`.
2. **M1 redaction ruling** made and implemented: audience is the primary external projection gate; `public` data classification may relax metric-data visibility but still strips physical schemas/tables, bound parameter names, limit metadata, and SQL fingerprints.
3. **M2 operator-503 test** added.
4. Concurrency bug **H1** (stale-claim reclaim race) fixed with observed claim-token CAS.

## 7. Boundaries

- `os_core` domain-independence intact (no imports of `examples/`/`domain_packs/`/`providers/`/`action_connectors/`; concrete connectors runtime-injected — `registry.py:12`).
- No R4/R5 auto-execution introduced; approval remains human-in-the-loop.
- Claim boundary unchanged: P5 governance + governed action only; no autonomy/G-Eco claim.
- A second API-key class is a **new credential/trust boundary** but stays within deployment-layer auth; broader RBAC/tenant-isolation/field-level authz remain explicitly future (per `CURRENT_STATE.yaml`).

---

## Disposition

**Accepted — merge of `codex/durable-action-ledger` is authorized** after M1, M2, and H1 remediation. The auth/redaction mechanism is accepted as a bounded deployment-layer surface; it does not authorize full RBAC/DLP, tenant isolation, field/row-level authorization, external release, external-system exactly-once, external ACK confirmation, durable arbitrary external connector recovery, or automatic R4/R5 execution.
