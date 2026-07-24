# AGENT-OS-TERMINAL-2 — Complete coding-agent terminal form

> Status: `IMPLEMENTING`
> Date: `2026-07-24`
> Branch: `codex/agent-os-terminal-2-20260724`
> Primary class: `P`
> U: Founder runs Agent OS like Codex/Claude Code/OpenCode — multi-tool task execution, not a chat shell

## Target form (peer parity map)

| Capability | Codex / Claude Code | TERMINAL-1 | TERMINAL-2 |
|---|---|---|---|
| Launch | one command | `agent-os` | same + `--resume` |
| Mission context | project rules | Mandate inject | Mandate + session resume |
| Read / search / glob | yes | read/search | + `workspace.glob` |
| Edit | apply_patch / Edit | full-file write | + unified diff apply |
| Shell (controlled) | yes | allowlisted argv | same + richer schemas |
| Tests | yes | pytest allowlist | same |
| Multi-turn tool loop | yes | yes | longer rounds + schemas |
| Continuation | agent loop | `--continue` | default-on with goal + stop tokens |
| Approval on writes | yes | y/N | y/N + session audit |
| Transcript / resume | yes | weak | durable session file |
| Streaming TUI | rich | plain | **out of V2** (plain + progress lines) |
| MCP | some | no | **out of V2** |

## V2 must ship together

1. `workspace.glob` — list paths by glob under `--repo`
2. `workspace.apply_patch` accepts either full-file `{path,content}` **or** `{diff: unified_diff}`
3. OpenAI tool JSON schemas for all terminal capabilities (not `additionalProperties: true` only)
4. Durable session: `.agent_os/terminal_session.json` save after turns; `--resume` / `/resume`
5. With an initial goal, `--continue` remains explicit OR `--agent` enables goal→auto-continue (alias)
6. Tests cover glob, unified diff apply, schema emission, resume

## Non-claims

- Not Rust/TS rewrite
- Not full Codex TUI/MCP parity
- Not Autonomy / HCW evidence
- Not release / push authorization by this doc alone

## Verify

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  python3 -m pytest tests/product/test_mandate_terminal*.py -q
```
