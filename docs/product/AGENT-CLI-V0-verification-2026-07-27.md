# Agent CLI V0 Verification

> Date: 2026-07-27
> Branch: `codex/agent-cli-v0-20260727`
> Worktree: `.worktrees/agent-cli-v0-20260727`
> Result: `TARGETED_GREEN / REVIEWED_WITH_REMEDIATION / LIVE_PROVIDER_PENDING_ENV`
> Claim ceiling: `IMPLEMENTED_LOCAL / TARGETED_TESTED / NOT_USABLE_ALPHA`

## Targeted tests

```text
uv run pytest tests/product/test_terminal_chat_loop.py tests/product/test_agent_cli_v0.py -q
29 passed
```

Coverage: governed AgentLoop (21) + Mandate zero-config / resume / confirmation
fail-closed / PolicyKernel events / clock-fixed ensure_local / REPL status /
resume mandate+workspace binding / `.agent_os` path reservation.

## Static

```text
uv run ruff check <changed agent-cli modules + tests>
All checks passed!

uv run pyright packages/os_core/src/agent_os_core/{agent_cli,mandate_terminal,terminal_session,agent_loop,action_pipeline,provider_receipts}.py
0 errors, 0 warnings, 0 informations
```

## Live provider

Fixture procedure: `docs/product/AGENT-CLI-V0-live-provider-fixture-2026-07-27.md`.
Status: `PENDING` — requires operator-approved load of local provider credentials;
process env at review time had no `AGENT_OS_PROVIDER_*` exported.

## Review

| Review | Result |
|---|---|
| Security Review | No medium+ findings; proposal-only + PolicyKernel path accepted |
| Bugbot | 2 high + 1 medium; remediated: resume Mandate/workspace binding, reserve `.agent_os` |
| Residual design debt | `workspace.run_tests` remains risk tier 1 (allowlisted pytest) while `workspace.shell` is tier 3 — accepted V0 product shape, not a synthetic-permit bypass |

Request artifact: `docs/product/AGENT-CLI-V0-independent-review-request-2026-07-27.md`.

## Non-claims

Not merged, not released, not usable-alpha, not Autonomy(S,E,O,V,T), not Data Agent
organ, not MCP/TUI parity.
