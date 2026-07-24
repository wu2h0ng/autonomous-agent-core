# Agent OS TERMINAL-3 (2026-07-24)

Status: `implemented` / `tested` (local). Claim class: **product runtime surface**, not Autonomy/HCW evidence.

## Scope

1. **Freer bash** — `workspace.shell` no longer program-allowlists; still denies `;|&`, backticks, `$()`, `${}`, redirects, newlines, and dangerous programs (`sudo`/`su`/…). `bash`/`sh`/`zsh -c` allowed under the same meta ban.
2. **MCP** — stdio JSON-RPC client (`terminal_mcp.py`), config `.agent_os/mcp.json` or `AGENT_OS_MCP_CONFIG`. Tools appear as `mcp.<server>.<name>` and require interactive approval (same as shell writes). Disable with `--no-mcp`.
3. **Streaming rich TUI** — `--tui` uses Rich Live when installed, else ANSI progressive fallback (`terminal_tui.py`). Provider path uses `complete_streaming` (OpenAI SSE when live).

Not Ink/Ratatui: Python-native equivalent surface by design.

## Usage

```bash
agent-os --agent "…"
agent-os --tui --agent "…"
agent-os --resume
# optional MCP
# .agent_os/mcp.json → servers.{name}.{command,args,env}
```

## Non-claims

Does not establish `Autonomy(S,E,O,V,T)` or HCW reduction. C7 / interactive approval for write+MCP remains.
