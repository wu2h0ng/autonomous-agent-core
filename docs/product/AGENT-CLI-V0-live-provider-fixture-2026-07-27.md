# Live provider fixture — Agent CLI V0

> Status: `PREPARED / NOT_RUN`
> Date: 2026-07-27

## Purpose

One frozen real-provider repository task under Mandate + AgentLoop to close the
live gate before any usable-alpha language.

## Required environment

```bash
export AGENT_OS_PROVIDER_BASE_URL=...
export AGENT_OS_PROVIDER_MODEL=...
export OPENAI_API_KEY=...   # or AGENT_OS_PROVIDER_API_KEY_ENV target
```

## Fixture procedure (operator)

1. Create an empty temp git repo with a failing pytest file (e.g. `assert False`).
2. From worktree:

```bash
cd autonomous-agent-core/.worktrees/agent-cli-v0-20260727
uv run python -m apps.cli --workspace /path/to/fixture --database /tmp/agent-cli-v0.sqlite3 \
  agent -p "Fix the failing test with the smallest edit, then run tests."
```

3. One-shot `-p` uses `AutoApproveGateway` for risk tier &lt; 3 (read/edit/tests).
   Tier ≥ 3 shell still requires interactive REPL confirmation and is rejected headlessly.
   Prefer interactive REPL without `-p` when shell approval is required.
4. Record transcript, `.agent_os/terminal_session.json`, Task/Run ids, and pytest outcome.

## Pass criteria

- Task completes with observed test green
- Events include ACTION_PROPOSED and POLICY_DECIDED for tool turns
- No synthetic permit path
- Claim remains below usable-alpha until independent review also passes

## Current result

`NOT_RUN` — provider env unset during 2026-07-27 verification.
