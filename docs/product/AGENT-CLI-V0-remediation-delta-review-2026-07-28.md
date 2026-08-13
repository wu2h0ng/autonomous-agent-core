# Remediation delta re-review — Agent CLI V0

> Date: 2026-07-28
> Reviewer identity: Claude (Anthropic) via Trae IDE — independent of writer
> (`cursor-agent`) and of first reviewer (Cursor Security Review + Bugbot)
> Branch: `codex/agent-cli-v0-20260727`
> Delta under review: `083f0c4..0f209c7` (single commit `0f209c7`
> "fix(product): clear Agent CLI review baseline debt")
> Prior verdict: `APPROVE_WITH_BASELINE_DEBT` at `9542a87`
> (`docs/product/AGENT-CLI-V0-independent-review-2026-07-27.md`)
> Remediation spec: `docs/product/AGENT-CLI-V0-review-debt-remediation-2026-07-27.md`
> Verdict vocabulary: `APPROVE` / `APPROVE_WITH_BASELINE_DEBT` / `REVISE_TO_SPEC` / `NO_APPROVE`
> Scope discipline: delta review only — V0/P1/streaming body was reviewed at
> `9542a87` and is not re-opened here.

## Verdict

**`APPROVE`** (remediation delta only)

All three baseline-debt items are closed by real implementation with
bypass-detecting tests, independently re-run by this reviewer. The stock
`agent -p` one-shot path with default streaming now completes the frozen live
fixture against real DeepSeek with no interactive approval and no synthetic
permit path.

## Re-verification performed by this reviewer (not writer evidence)

| Check | Command / method | Result |
| --- | --- | --- |
| Targeted suite | `uv run pytest tests/product/test_terminal_chat_loop.py test_agent_cli_v0.py test_agent_cli_p1.py test_agent_cli_stream.py test_agent_cli_review_debt.py -q` | **48 passed** (writer claim reproduced) |
| Ruff | changed code + test files | All checks passed |
| Pyright | `agent_cli.py` `mandate_terminal.py` `terminal_session.py` | 0 errors, 0 warnings |
| Frozen live fixture, stock `agent -p` + streaming, DeepSeek `deepseek-chat` | fresh git-repo fixture with failing `add(a,b)`; fresh database | exit 0; `broken.py` → `return a + b`; pytest **1 passed**; summary at `docs/product/AGENT-CLI-V0-live-run-summary-2026-07-28.json` |
| Governed path on live run | event store inspection | 5× ACTION_PROPOSED + 5× POLICY_DECIDED + 5× ACTION_RECEIPT_RECORDED; every permit PolicyKernel-issued and bound to `policy_decision_id`; `approval_id=approval:none`; no synthetic permit |
| Session sidecar | `.agent_os/terminal_session.json` | schema `agent-cli-session.v1`, resolved `database` bound |

## Debt-item closure

1. **One-shot `-p` policy contradiction (high)** — CLOSED. `apps/cli/__main__.py`
   selects `AutoApproveGateway` when `args.prompt is not None`;
   `AutoApproveGateway.confirm` admits only `risk_tier < 3`. Tier ≥ 3 shell is
   still rejected headlessly. Coverage: gateway-selection unit test, subprocess
   E2E tier-2 edit auto-approve (would fail under the old deny gateway), and a
   new tier-3 shell deny test. Live fixture exercised the real path: tier-2
   `workspace.edit` auto-admitted, tier-1 `workspace.run_tests` admitted, no
   interactive prompt.
2. **`database` not bound on resume (high)** — CLOSED. Session schema bumped to
   `agent-cli-session.v1` with required resolved `database`; resume checks both
   the saved record and the attached Mandate against resolved `--database`;
   `ensure_local_mandate_session` fail-closes on attach/database mismatch
   instead of silently re-creating. Old v0 sidecars fail closed. Coverage:
   mismatch, tampered sidecar, and `ensure_local` mismatch tests.
3. **Resume of dead/halted runs (medium)** — CLOSED. Resume rejects run
   statuses outside `{RUNNING, QUEUED, PAUSED, WAITING_EVENT, WAITING_APPROVAL}`
   and runs halted per `correction.halted`, which checks task, run, and the
   probed capability epoch scopes — task-level `correct_task` halts are caught.
   Coverage: terminal-status and correction-halted rejection tests.

## Findings

- **Low (docs debt, writer scope)** — The frozen fixture doc command
  `uv run python -m apps.cli ...` does not run as written: the monorepo
  packages are not installed into the uv environment (tests work only via
  pytest `pythonpath` ini). The live run requires
  `PYTHONPATH=.:src:packages/contracts/src:packages/os_core/src`
  (same as `_cli_env` in `test_terminal_chat_loop.py`). Recommend the writer
  amend `AGENT-CLI-V0-live-provider-fixture-2026-07-27.md` (which also still
  reads `Current result: NOT_RUN`) to record the 2026-07-28 rerun and the
  PYTHONPATH requirement. Not a runtime defect; does not block this verdict.
- **Observation (non-blocking, already noted by first reviewer)** — `-p`
  auto-admission trusts declared capability risk tiers (`< 3`). A future
  mis-tiered capability would be auto-admitted headlessly. Keep the AWL
  `risk_tier` vs capability-floor note tracked.
- **Observation (non-blocking)** — The resume correction probe checks
  task/run epochs plus the `provider` capability scope. A halt scoped only to
  another capability does not block resume but surfaces fail-closed downstream
  via epoch guards.

## Open questions

None blocking. Whether `-p` auto-approve (tier < 3) is the permanent one-shot
product policy remains a founder/product decision; the GC and fixture doc now
describe it consistently.

## Required changes

None for this delta. The fixture-doc amendment above is writer-scope docs debt.

## Claim ceiling (unchanged)

`IMPLEMENTED_LOCAL / TARGETED_TESTED / REVIEW_DEBT_REMEDIATED_VERIFIED` —
not usable-alpha, not release, not Autonomy(`S,E,O,V,T`), not MCP/TUI/sub-agent
parity. Push, merge and release remain outside reviewer authority; merge
authorization is requested from the founder via PR.

## Evidence pins

- Delta diff: `git diff 083f0c4..0f209c7`
- Live summary: `docs/product/AGENT-CLI-V0-live-run-summary-2026-07-28.json`
- Live transcript (local): `/tmp/agent-cli-live-20260728-transcript.log`
- Task ledger: `.agent_runs/agent-cli-v0-20260727/messages.jsonl`
