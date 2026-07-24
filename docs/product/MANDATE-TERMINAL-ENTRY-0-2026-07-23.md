# Mandate Terminal Entry 0

> Status: `IMPLEMENTED_LOCAL / SUPERSEDED_INTERACTION_BY_TERMINAL_1 / NO_AUTONOMY / NO_HCW_CLAIM`
> Date: `2026-07-23`
> Branch: `codex/mandate-terminal-entry-20260723`
> Primary class: `P` (U: founder operates Mandate via standard terminal agent, not coding-agent chat)

## Product entry (this is the agent)

Usage matches `codex` / `kimi`: install or put `bin/agent-os` on `PATH`, then type the agent name.

```bash
# install name on PATH (pick one)
ln -sf "$(pwd)/bin/agent-os" ~/.local/bin/agent-os
# or: pip install -e .

# once: admin bootstrap + attach
agent-os --database ~/mandate.sqlite3 --workspace ~/mandate-ws \
  mandate-bootstrap mandate.json --relevance-context context.json
agent-os --database ~/mandate.sqlite3 --workspace ~/mandate-ws \
  mandate-attach --mandate-id ... --environment-binding-id ... \
  --principal-id ... --tenant-id ... --workspace-id ...

# standard terminal agent — bare name launches REPL
agent-os --database ~/mandate.sqlite3 --workspace ~/mandate-ws
agent-os --database ~/mandate.sqlite3 --workspace ~/mandate-ws "what is open?"
agent-os --database ~/mandate.sqlite3 --workspace ~/mandate-ws --offline
```

Inside the REPL:

| Input | Behavior |
|---|---|
| free text | Provider chat with Mandate status injected as SYSTEM (no paste) |
| `/status` | Re-print durable mission / commitments |
| `/help <question>` | Structured HelpRequest to durable inbox |
| `/quit` | Exit |

Live model requires `AGENT_OS_PROVIDER_BASE_URL` (+ API key env). Without it, REPL still boots with Mandate context and uses DeterministicProvider text.

## Admin surface (not the agent)

`mandate-bootstrap` / `mandate-attach` / `mandate-status` / `mandate-help-request` remain JSON ops for setup and inspection.

## Non-claims

- Not Autonomy / AGI / product superiority
- Not HCW reduction evidence until founder operates through this REPL as the surface
- Coding tools: see successor `AGENT-OS-TERMINAL-1-2026-07-24.md` (V0 tool loop)
- Not full Codex/Claude Code/OpenCode parity
- Not production release

## Verification

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  python3 -m pytest tests/product/test_mandate_terminal.py tests/product/test_mandate_repl.py -q
```
