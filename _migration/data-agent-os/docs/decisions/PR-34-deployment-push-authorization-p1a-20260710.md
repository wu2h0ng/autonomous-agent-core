# PR-34: Authorized origin/main push of P1-A (ADR-0014 choice-set + seam-escalation fix)

- Date: 2026-07-10
- Status: **Option B executed by founder cast ("解部署 HOLD"), then re-HELD** — one authorized `origin/main` push, HOLD restored immediately after.
- Supersedes: PR-33 Option A HOLD **for this single push only**. The "no more P1 feature slices under the controlled-pilot maintenance boundary" boundary in PR-33 is explicitly waived by the founder for this reviewed governance/safety feature; it is NOT a general lift.
- Active machine token (post-push, durable): **`DEPLOYMENT_PUSH: HOLD`** — see PR-33 / PR-11; the gate is fail-closed again after this push.

## What was authorized
A single fast-forward promotion of the reviewed P1-A feature family to `origin/main`:
`origin/main fed54d6 → <P1-A head>` (the ADR-0014 approval choice-set contract + the seam-escalation bypass fix + fast-follow comment nit).

## Why it is safe to land
- **ADR-0014 mechanism**: every human-approval proposal must carry a real choice set (≥2 alternatives, one recommended, covering candidate_actions) OR a truthful single_option_rationale; a fail-closed invariant refuses violations at the proposal step.
- **HIGH bug found and fixed under cross-model review**: the original commit (`82a8554`) let the governance seam escalate a propose-only proposal into human approval AFTER the invariant, reaching the approver with a blank single option. Fixed by a post-seam re-gate (attach a truthful escalation rationale + re-run the invariant + block if still degenerate) and a durable ApprovalRecord choice-set snapshot so GET /approvals/{id} survives execution.
- **Three-model validation loop (build ≠ review)**: Claude subagent built; OpenCode wrote independent acceptance tests (9/9 valid pass; 2 adjudicated over-specified); Kimi reviewed the diff → ACCEPT-WITH-NITS, "HIGH bypass GENUINELY CLOSED"; CTO confirmed the public GET surface + verified the one remaining unit failure (S6 domain-independence) is a pre-existing branch-only artifact that self-resolves once the change is on main (`git diff main...HEAD` becomes empty).
- **CI at the pushed head**: `make lint` / `make format-check` (271 formatted) / `make anti-stub-lint` / `make openapi-contract` (up to date) / `make eval` (12 OK) all green; full unit suite green except the self-resolving S6 assertion.

## Gate procedure followed (PR-33 §"How to flip", adapted)
1. Content committed so the tip SHA is known (this doc + CURRENT_STATE header update ride with the P1-A commits).
2. `scripts/release_gate/push_authorization_check.py` set AUTHORIZED **transiently** with `candidate_head: <pushed-40-char-sha>`, run with `--expected-head <sha>` → **exit 0** (recorded at push time).
3. Only that commit family pushed to `origin/main` (fast-forward; `fed54d6` is an ancestor).
4. The transient AUTHORIZED token reverted to `DEPLOYMENT_PUSH: HOLD` immediately (this record + PR-33 remain HOLD), so no subsequent tip is accidentally authorized.

## Boundaries (unchanged — this push does NOT authorize any of these)
- No release tag / RC tag push (separate gate).
- No external GA or public product claim.
- No default-on staged feature flags.
- R4/R5 automatic execution remains proposal-only (ADR-0012 gating unchanged).
- Merging the S1–S4 real-execution RC into product mainline remains a separate reserved safety gate.
- P2 (approval analytics / ledger preview / evidence confidence) lands under its own per-slice PR-34-style authorization, not this one.

## Follow-ups (tracked, non-blocking)
- Fold the OpenCode independent acceptance suite (`test/adr-0014-seam-acceptance-20260710`) into the main test suite after fixing its 2 over-specified (context-store-internal) assertions to check the public GET/ApprovalRecord surface.
- Optional transparency enhancement: surface the seam-escalation reason on the approval UI even when a builder single_option_rationale already exists (currently trace-only; documented as accepted).
- S6 integration test compares `main...HEAD`, which false-fails on any core-touching feature branch; consider re-baselining it against the slice's own baseline.
