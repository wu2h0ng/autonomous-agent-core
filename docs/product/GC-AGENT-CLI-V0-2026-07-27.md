# Goal Card — Agent CLI V0 (Mandate-top + governed SE organ)

> Date: 2026-07-27
> Track: Product
> Status: **SPEC_APPROVED / V0_IMPLEMENTATION_AUTHORIZED / NO_RELEASE**
> Branch: `codex/agent-cli-v0-20260727`
> Base: `origin/main`
> Claim ceiling before review + live provider: `IMPLEMENTED_LOCAL / TARGETED_TESTED` only

## Goal

Ship a single Agent OS terminal entry comparable in *product shape* to Hermes /
OpenClaw / Pi: operator launches one CLI, works under a durable Mandate, and the
runtime executes through a governed multi-turn model⇄tool loop. Software
engineering (read/search/edit/test/allowlisted-shell) is an **organ**, not the
product name.

## Requirement taxonomy

- `U` — operator advances Mandate-scoped work from one terminal without pasting
  identity/context every turn.
- `P` — Agent CLI V0 (this package). Primary label.
- `A` — model output is proposal-only; every consequential action passes
  PolicyKernel → exact permit → CapabilityBroker; C7 correction remains
  non-bypassable.
- `E` — bypass-detecting tests, targeted green suite, review packet.
- `R` — none. No Autonomy(S,E,O,V,T) claim.

## Done conditions (V0)

1. Single entry: `agent-os` / `python -m apps.cli` defaults into Agent REPL.
2. Zero-config local Mandate boot + `/status` shows Mandate + session ids.
3. SE organ runs via `AgentLoop` (PolicyKernel path), not terminal-minted permits.
4. Durable transcript `--resume` / `/resume` bound to mandate/task/run ids.
5. Targeted tests green; independent review materials prepared; one live-provider
   fixture attempted or explicitly `NOT_RUN` with env gap recorded.

## Explicit non-goals (V0)

Data Agent organ, SPINE-1 migration, MCP, sub-agents, rich TUI, arbitrary shell,
OS sandbox, usable-alpha, release, autonomy evidence.

## Stop / REVISE_TO_SPEC

- Synthetic terminal permits as the formal authority path
- Model output executed without proposal/policy/permit
- Mixing this work into the dirty AWL tree
- Claiming general agent completeness or Autonomy from V0
