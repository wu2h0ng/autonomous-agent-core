# PR-35: Authorized origin/main push of the P2 batch (deployment product depth)

- Date: 2026-07-10
- Status: **Option B executed by founder cast ("批准 P2 批次上产品主线"), then re-HELD** — one authorized `origin/main` push of the P2 batch, HOLD restored immediately after.
- Supersedes: PR-33 HOLD / PR-34 (P1-A) **for this single push only**. The "no more P1 feature slices" boundary was already waived by the founder for P1-A (PR-34); this record authorizes the P2 product-depth batch on top of it.
- Active machine token (post-push, durable): **`DEPLOYMENT_PUSH: HOLD`** — the gate is fail-closed again after this push.

## What was authorized
A single fast-forward promotion of the reviewed P2 batch to `origin/main`:
`origin/main 1bdf280 → <P2-C-head-family>` (chained: 1bdf280 → P2-A → P2-B → P2-C), plus this record + the CURRENT_STATE update.

## The P2 batch (all built test-first, three-model validated, build≠review held)
- **P2-A** (`ADR-0015`) — approval rubber-stamp analytics + a `revise` outcome. Per-tenant/risk modify-rate + selection-concentration MEASURED (derived from selected_action vs recommended_action, not operator-self-reported); the `/execute` primary path records an implicit `approved_recommended` so straight-execute rubber-stamps are counted. The production falsifier for ADR-0014.
- **P2-B** (`ADR-0016`) — ledger consequence preview. Symbolic honest counts from the durable action_records ledger ("N prior executions, M resolved"), attached as EvidenceChain evidence on `GET /approvals/{id}`; fail-safe (available=false on ledger error), tenant-isolated, no prediction. Strengthens the ADR-0008 outcome moat.
- **P2-C** (`ADR-0017`) — EvidenceChain confidence derivation. Replaced the static 0.55/0.82 with a transparent rule-based derivation from source freshness + row_count + template-verification (inputs recorded + recomputable), plus a τ-consistency boundary at the DataProduct→EvidenceChain seam. `source_age_seconds` is a provider-reported optional signal; honestly capped + flagged when absent (never defaults high).

## Validation summary
Each slice: Claude subagent built test-first / OpenCode wrote independent acceptance tests / Kimi reviewed the diff (ACCEPT or ACCEPT-WITH-NITS) / CTO ran an independent full-suite CI + adjudicated. Full unit suite green on the P2-C head modulo the self-resolving controlled-pilot-readiness release-gate env check (remote-head pin, reconciled locally post-push per PR-15's protocol). `make lint / format-check / anti-stub-lint / openapi-contract / eval` green.

## Gate procedure followed (PR-33 §"How to flip", adapted — same as PR-34)
1. Content committed so the tip SHA is known (this doc + CURRENT_STATE update ride with the P2 commits).
2. `push_authorization_check.py` set AUTHORIZED **transiently** with `candidate_head: <pushed-40-char-sha>`, run with `--expected-head <sha>` → exit 0.
3. Only that commit family pushed to `origin/main` (fast-forward; `1bdf280` is an ancestor).
4. The transient AUTHORIZED token reverted to `DEPLOYMENT_PUSH: HOLD` immediately (committed PR-33/PR-11/PR-34 tokens never flipped).
5. `PR-15` "Remote main head" pin advanced to the new `origin/main` as a local docs commit (PR-15's documented protocol), restoring the controlled-pilot-readiness gate.

## Boundaries (unchanged — this push does NOT authorize any of these)
- No release tag / RC tag push (separate gate). No external GA / public product claim. No default-on feature flags.
- R4/R5 automatic execution remains proposal-only (ADR-0012 unchanged).
- Merging the S1–S4 real-execution RC into product mainline remains a separate reserved safety gate.
- P3 (object-layer research) and P4 (release governance / GA) remain founder-gated.

## Follow-ups (tracked, non-blocking)
- P2-A LOW: /decision reachable only via internal X-API-Key not the operator key channel; tenant query-param admin-global; per-approval decision public read.
- P2-B LOW: `evidence_to_payload` doesn't round-trip the preview (legacy fallback dead; primary ApprovalRecord snapshot works); ADR note that the preview is internal-audience deliberation evidence.
- P2-C LOW: negative `source_age_seconds` guard; per-provider freshness wiring (report the source's actual data age so the freshness factor fires beyond the honest-unknown cap).
- Release-gate wart: the controlled-pilot-readiness "Remote main head" pin cannot equal the pushed commit's own hash (self-reference); it is reconciled as a local docs commit post-push. A descendant-based check would remove the perpetual local-ahead pin.
