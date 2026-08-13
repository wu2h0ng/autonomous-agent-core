# Architecture Brief — Agent CLI V0

> Date: 2026-07-27
> Goal Card: `docs/product/GC-AGENT-CLI-V0-2026-07-27.md`

## Decision

One terminal surface. Mandate is the top object. Software engineering runs as a
governed organ through `AgentLoop` beside the static `WorkflowGraph` executor.

```text
operator → agent-os [agent]
        → ensure_local_mandate_session / attach
        → open_chat_session (Task+Run sealed)
        → AgentLoop.run_turn
             provider proposals only
             → PolicyKernel.decide → permit → CapabilityBroker
             → TOOL feedback
        → terminal_session.json (mandate/task/run/session + messages)
```

## Rejected

1. Permanent split of `chat` vs `mandate` as two products
2. V3 `MandateToolRuntime` locally minted permits
3. MCP / freer bash in V0
4. AWL `execution.py` decomposition as a dependency of the loop

## Modules

| Module | Role |
|---|---|
| `mandate_terminal.py` | zero-config Mandate boot/attach/status |
| `agent_cli.py` | REPL bridge Mandate ↔ AgentLoop + resume |
| `terminal_session.py` | durable transcript |
| `agent_loop.py` | governed SE organ loop |
| `action_pipeline.py` | build/propose/decide/permit/invoke |

## Claim boundary

`IMPLEMENTED_LOCAL / TARGETED_TESTED` after green targeted tests. Live provider,
independent review acceptance, usable-alpha, and release remain separate gates.
