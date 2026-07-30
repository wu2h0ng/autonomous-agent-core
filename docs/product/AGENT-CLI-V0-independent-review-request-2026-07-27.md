# Independent review request — Agent CLI V0

> Date: 2026-07-27
> Branch: `codex/agent-cli-v0-20260727`
> Base: `origin/main`
> Worktree: `autonomous-agent-core/.worktrees/agent-cli-v0-20260727`
> Requested verdict vocabulary: `APPROVE` / `APPROVE_WITH_BASELINE_DEBT` / `REVISE_TO_SPEC` / `NO_APPROVE`

## Scope

Exact diff of Agent CLI V0 synthesis:

- Mandate zero-config terminal helpers (`mandate_terminal.py`)
- Durable session (`terminal_session.py`)
- Mandate ↔ `AgentLoop` bridge (`agent_cli.py`)
- Governed SE organ loop (`agent_loop.py` + `action_pipeline.py` + capability/provider/contract deltas)
- Unified CLI entry (`apps/cli/__main__.py`)
- Tests: `test_terminal_chat_loop.py`, `test_agent_cli_v0.py`

## Must verify

1. No synthetic terminal-minted permits; every tool action uses PolicyKernel → permit → broker.
2. Model output cannot become workspace effects without `ProviderToolProposal` + policy path.
3. Session resume does not invent authority or skip Task/Run sealing.
4. Clock-fixed `ensure_local_mandate_session` cannot attach with invalid evaluated_at windows.
5. `chat` is alias only; product entry is `agent`.
6. No MCP / arbitrary shell / AWL execution rewrite smuggled in.

## Evidence already local

- Targeted: 27 passed
- Ruff clean on changed modules; Pyright 0 on listed core modules
- Goal/Context/Architecture: `docs/product/GC|CP-AGENT-CLI-V0-2026-07-27.md`, `docs/architecture/A-AGENT-CLI-V0-2026-07-27.md`
- Verification: `docs/product/AGENT-CLI-V0-verification-2026-07-27.md`

## Out of reviewer authority

Push, merge, release, usable-alpha, Autonomy claims.
