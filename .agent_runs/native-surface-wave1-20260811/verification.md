# Agent OS Native Surface Wave 1 — Verification Report

- Plan base SHA: `7bfb1753` (docs: specify native Agent OS surface program)
- Plan commit: `fff9cb50` (docs: plan native surface wave 1)
- Implementation head: `641cc8477360a4378deeaae32b7e2001411d893f`
- Branch: `codex/native-surface-wave1-20260811`
- Worktree: `autonomous-agent-core/.worktrees/native-surface-wave1-20260811`
- Date: 2026-08-12
- Authority ceiling: local implementation and verification only; NO push, merge, release, signing, notarization, live-provider request, or current-state completion claim is authorized by the plan.

## Scope delivered

- Task 1: closed Surface protocol contracts (surface.py) — APPROVED
- Task 2: durable session transcripts + strict projection — APPROVED
- Task 3: restartable AgentLoop with durable history — APPROVED
- Task 4: durable deferred-approval continuation; lease-fenced execution ownership; C7 dispatch linearization; runnable-Run provider fence — APPROVED at `2615b10e`
- Task 5: concurrency-safe `SurfaceRuntime` (per-session serialization, idempotency/digest, sequence, scope gates) — APPROVED at `1a82e6a5`
- Task 6: authenticated HTTP + resumable SSE; daemon-mode auth over all `/v1/*`; no 4xx idempotency poisoning — APPROVED at `447f4dd9`
- Task 7: `RuntimeDescriptor`, stdlib `SurfaceClient`, CLI chat + session-* via descriptor (no daemon SQLite open); `agent-os` console script — APPROVED at `9bcd22fb`
- Task 8: atomic 0600 descriptor writes, live/stale descriptor logic, SIGTERM cleanup with boot-id match, `agent-os-runtime` serve, `daemon-start/status/stop` — APPROVED at `641cc847`
- Task 9: Wave 1 E2E gate + this evidence

## Commands and exact results

Focused Wave 1 verification (9 suites + E2E):

```bash
uv run --extra product-test pytest \
  tests/product/test_surface_contracts.py \
  tests/product/test_session_projection.py \
  tests/product/test_surface_runtime.py \
  tests/product/test_surface_api.py \
  tests/product/test_surface_client.py \
  tests/product/test_runtime_daemon.py \
  tests/product/test_cli_surface.py \
  tests/product/test_terminal_chat_loop.py \
  tests/product/test_surface_wave1_e2e.py -q
```

Result: **184 passed in 27.01s**

Wave 1 E2E gate (`test_surface_wave1_e2e.py::test_cli_and_protocol_client_share_one_restartable_coding_session`): **PASSED** — open session -> run_turn (WAITING_APPROVAL) -> real daemon restart (new descriptor, same SQLite) -> get_session preserves pending approval -> decide_approval(APPROVE, exact digest) -> completed, fixture `fixed\n`, exactly one `ACTION_RECEIPT_RECORDED`, CLI `session-show` event_sequence == completed snapshot event_sequence.

Full Product regression:

```bash
uv run --extra product-test pytest tests/product -q
```

Result: **1792 passed, 18 failed, 1 skipped** (head, including the E2E gate test) vs **1625 passed, 18 failed, 1 skipped** (exact base `7bfb1753` in a pristine temp worktree). Failure sets are byte-identical (16 `test_provider_trajectory_binding.py` fixed-date cases, `test_spine0_golden_path.py::test_developer_golden_path_real_read_patch_tests_and_outcome`, `test_spine0_security_and_persistence.py::test_correction_after_permit_blocks_actual_dispatch` — the last is order-sensitive and passes in isolation at both head and base). All 18 are classified PRE-EXISTING, not Wave 1 regressions.

Full Product + product_eval:

```bash
uv run --extra product-test pytest tests/product tests/product_eval -q
```

Result: **2711 passed, 28 failed, 1 skipped**. 27 of the 28 reproduce at the exact base. The 28th (`test_spine_e2e_4_scratch_cli.py::test_scratch_fixture_is_disjoint_from_absent_formal_output_ledgers`) fails because the test resolves `WORKSPACE` to the shared parent workspace (`AI-Agent-Projects`) whose `.agent_runs/spine-e2e-4-20260713/` contains stale 2026-07-13/14 artifacts; this is independent of any Wave 1 change (the test passes at the base when the enclosing checkout has no such stale directory). Classified PRE-EXISTING ENVIRONMENTAL, not a Wave 1 regression.

Static checks:

```bash
uv run --extra product-test ruff check apps packages/contracts/src packages/os_core/src tests/product
uv run --extra product-test pyright apps packages/contracts/src packages/os_core/src tests/product
git diff --check
```

Result: Ruff clean; Pyright 0 errors on all Wave 1 paths (apps/, os_core surface paths, tests); `git diff --check` clean.

## Daemon restart transcript (E2E)

1. `start_runtime_process` daemon #1 (repair script): descriptor `runtime-1.json` published; provider proposes `workspace__edit`.
2. `SurfaceClient.open_session("repair the failing fixture")` -> snapshot ACTIVE.
3. `run_turn("inspect and repair")` -> `stop_reason=approval_required`, snapshot WAITING_APPROVAL, pending approval carries exact action digest.
4. `daemon.stop()` -> SIGTERM; descriptor removed by boot-id-matched cleanup; SQLite closed.
5. `start_runtime_process` daemon #2 (finish script): new descriptor `runtime-2.json`, same database.
6. `get_session` -> pending approval intact (durable), status WAITING_APPROVAL.
7. `decide_approval(APPROVE, exact digest)` -> action executes once (lease-acquired, fenced reservation), provider continuation completes; `stop_reason=completed`; fixture now `fixed\n`; exactly one effect receipt.
8. `agent-os session-show` CLI subprocess against daemon #2 -> `event_sequence` equals the completed snapshot's.

## No-live-provider boundary

All verification used the deterministic stub provider (`DeterministicProvider` or the scripted HTTP stub). No live-provider request was made; no release or daily-usability claim is established.

## Remaining risks and carried items

- HTTP-level coverage gaps (403/404/503/Last-Event-ID-vs-after disagreement / route-session bind mismatch) are probe-verified but not all shipped as tests (Task 6 minor).
- daemon health-timeout path is probe-only (Task 8 minor, recorded).
- APPROVE-on-PAUSED refusal error message is functionally correct but wording is misleading (agent_loop.py).
- Postgres guarded-insert expiry comparison relies on aware-datetime equality; non-UTC DSN sessions fail closed (safe direction).
- REPL surfaces raw tracebacks on daemon errors.
- CLI default principal (`user:local/tenant:local/workspace:local`) is a Wave 1 single-principal assumption.
- 18 pre-existing `tests/product` failures and 28 `tests/product + product_eval` failures (27 reproducible at base + 1 environmental) are not fixed by Wave 1.

## Claim ceiling

`IMPLEMENTED / TESTED / INTEGRATED / REVIEWED` on the branch; `PUSHED`, `RELEASED`, `DAILY_USABLE` and `NOT_MERGED` are explicit false. No autonomy, general intelligence, release, customer, or daily-usability claim.
