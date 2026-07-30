# Goal Card — Agent CLI P1 (AGENTS.md context + trusted shell profile)

> Date: 2026-07-27
> Track: Product
> Status: **P1_IMPLEMENTATION_AUTHORIZED / NO_RELEASE**
> Branch: `codex/agent-cli-v0-20260727`
> Base: Agent CLI V0 on same branch
> Claim ceiling: `IMPLEMENTED_LOCAL / TARGETED_TESTED` only

## Goal

Extend Agent CLI V0 with workspace agent-context discovery and a bounded
trusted shell profile so terminal sessions inherit project `AGENTS.md` guidance
and can run a small set of read-only git / lint / test commands without
widening graph or CI sandbox defaults.

## Requirement taxonomy

- `U` — operator's terminal agent sees project-specific guidance without
  manual paste each session.
- `P` — AGENTS.md discovery/injection + trusted shell profile for Agent CLI.
- `A` — symlink/outside-workspace AGENTS.md fail closed; shell remains
  exact-string allowlist only; tier-3 shell still requires confirmation.
- `E` — bypass-detecting tests in `test_agent_cli_p1.py`; targeted suite green.
- `R` — none.

## Done conditions (P1)

1. `discover_agents_markdown` returns path, sha256, truncated content; omits
   missing file; rejects symlinks.
2. Agent CLI system prompt includes `# Project AGENTS.md (sha256=…)` section.
3. `/status` exposes `agent_context` digest payload.
4. Agent CLI applies `TRUSTED_SHELL_PROFILE_V1` to its sandbox instance.
5. Targeted V0 + P1 tests green; no commit/push from implementation agent.

## Explicit non-goals (P1)

Arbitrary shell, MCP, sub-agents, parent-directory AGENTS.md walk, release,
autonomy evidence, weakening non-CLI sandbox paths.

## Stop / REVISE_TO_SPEC

- Reading AGENTS.md via symlink or outside workspace
- `shell=True` or prefix/wildcard allowlist matching
- Claiming V0+P1 as usable-alpha or release
