# Terminal Coding Agent Goal Card — Governed Multi-Turn Agent Loop and stdlib REPL (M0 + M1)

> Date: 2026-07-26
> Track: Product
> Status: **SPEC_APPROVED / M0_GOVERNANCE_DOCS_AUTHORIZED / M1_LOCAL_TDD_IMPLEMENTATION_AUTHORIZED / NO_RELEASE_AUTHORITY**
> Exact base: `27337578e15f307bec18edb5221356d5c3ed6c04` (`feature/awl-3-coordinator-decomposition`; M1 implementation requires its own feature branch)
> Authority: founder-approved route-A plan (terminal coding agent on the existing governance kernel)
> Claim ceiling before implementation review: `SPECIFIED_ONLY`
> Context Pack: `docs/product/CP-TERMINAL-CODING-AGENT-M0-M1-2026-07-26.md`
> Architecture Brief: `docs/architecture/T-P-CORE-TERMINAL-CODING-AGENT-ARCHITECTURE.md`
> Dated benchmark: `docs/product/TERMINAL-AGENT-CLI-BENCHMARK-2026-07-26.md` (Hermes / OpenClaw / Pi, with Claude Code / Codex CLI as product-shape references)

## Goal

Build, on top of the existing governance kernel, a terminal coding agent comparable in
product shape to Hermes, OpenClaw, Pi, Claude Code and Codex CLI: a governed multi-turn
conversation loop in which the model proposes typed tool calls, every executed call
passes `PolicyKernel.decide` + `ActionPermit` + correction-epoch validation, tool
results feed back as `TOOL` messages, and a stdlib REPL exposes the loop as
`python -m apps.cli chat`.

The user-facing outcome (`U`): an operator can point the CLI at a real workspace and
have the agent complete one real coding task — edit files and run tests — over multiple
turns, with full permit/audit/evidence coverage and an approval prompt for any
consequential action.

The product capability (`P`): a new `agent_loop` execution form coexisting with the
static `WorkflowGraph` executor, plus the contract, provider, capability and CLI
extensions that make the loop real end to end.

M0 is this governance packet (Goal Card + Context Pack + Architecture Brief). M1 is the
vertical slice defined below. M2–M4 are recorded as design direction only and are not
authorized by this card.

## Why this is the next slice

The governance kernel already has every authority primitive a coding agent needs —
typed provider contracts with a `TOOL` role, a policy kernel issuing per-action permits,
a capability broker with sandboxing/compensation/correction epochs, and event-sourced
durable execution — but its only execution form is a static `WorkflowGraph` and its only
model-driven path is a single-turn hard-coded proposal engine. There is no multi-turn
conversational execution form and no interactive entry point. This slice adds exactly
that missing form without weakening any existing invariant, and it is the smallest slice
that produces a user-perceptible outcome (a working terminal coding session) rather than
another internal mechanism.

## Requirement taxonomy (root constitution §9A)

Primary labels for this task package:

- `U` — terminal coding assistance: the operator delegates a bounded coding task in a
  REPL and receives verified file edits plus test results.
- `P` — the governed agent loop, its capabilities and the CLI entry point that
  implement that `U`. This is the primary label of the package.
- `A` — the authority invariants that protect the `U`: no path around
  `PolicyKernel.decide` / permit / correction epoch (C7); model output only ever
  becomes a `ProviderToolProposal`; Agent Core stays domain-independent.
- `E` — engineering acceptance: bypass-detecting tests, targeted + Product-suite test
  runs, ruff, pyright, wheel builds, independent review.
- `R` — none. This package makes no research claim and produces no autonomy evidence.
  Any future `Autonomy(S,E,O,V,T)` statement would require a separate Research Track
  package; interactive orchestration progress here is not autonomy evidence.

Per-milestone labels and claim levels are tracked in the Architecture Brief §10.

## Inputs and outputs

### Allowed inputs

- operator text input in the REPL (`chat`) or a single prompt (`chat -p "..."`);
- a workspace root the sandbox already governs;
- provider credentials/config through the existing provider configuration path;
- an approval decision (`y/n`) in the REPL when the policy verdict requires approval.

The model may not supply its own permit, verdict, epoch, approval, capability scope or
storage write. The operator may not inject provider messages, tool results or receipts
outside the typed contract path.

### Outputs

- a durable Task/Run event stream (existing event store / SQLite, no second storage
  system) recording turn metadata, provider responses/receipts, proposed actions,
  verdicts, permits and action receipts; live message history remains in memory in M1,
  so replay/resume is explicitly not claimed;
- real workspace effects produced only through brokered capabilities with snapshot
  compensation;
- a terminal transcript showing assistant text, tool-call summaries and approval
  prompts;
- `ProviderExecutionReceipt` records per provider call, reusing the existing receipt
  construction.

## Authority and identity condition

- Every capability invocation in the loop goes through `PolicyKernel.decide`, an
  `ActionPermit` issued for that exact action, and correction-epoch validation. READ_ONLY
  capabilities may auto-pass policy; edit/shell-class capabilities require a verdict,
  which in interactive mode surfaces as a terminal confirmation mapped onto the existing
  approval signal path.
- Model output never becomes a command. It is parsed into `ProviderToolProposal`
  objects and nothing else reaches the broker.
- Ctrl-C maps to a correction halt through the existing correction authority, never to
  an out-of-band process kill that skips the event record.
- No new authority spine, no second policy kernel, no capability registration that
  skips the broker.

## Done conditions

M0 is done when this Goal Card, the Context Pack and the Architecture Brief exist in the
locations named in the header and the founder CTO gate has accepted them. M0 authorizes
documentation only.

M1 may be called locally implemented only after all of the following are true:

1. `ProviderMessage` carries optional `tool_call_id` / `tool_calls`; `SessionRef` and
   `TurnId` are typed contracts with tests.
2. `OpenAICompatibleProvider` serializes TOOL messages and ASSISTANT `tool_calls`;
   `DeterministicProvider` supports scripted multi-turn response sequences.
3. `workspace.edit` (exact string replacement, uniqueness check, snapshot
   compensation), `workspace.search` (stdlib glob/grep/ls, truncated output) and
   `workspace.shell` (allowlist + risk-tiered verdict, timeout, truncated output,
   artifact capture) are registered capabilities, each with failure paths for illegal
   path, expired permit and epoch drift, and each introduced by a failing /
   bypass-detecting test first (AGENTS.md §4).
4. `AgentLoop.run_turn()` executes the full cycle
   `provider → proposals → per-proposal decide/permit/invoke → TOOL-message feedback →
   provider`, and stops on no-proposal, turn cap, token budget, retryable-failure
   exhaustion or repeated-digest loop detection.
5. `python -m apps.cli chat` starts an interactive REPL with `/exit` and `/status`;
   `chat -p "..."` runs one non-interactive prompt and fails closed on any action that
   needs terminal confirmation; approval-required actions display the diff/command and
   wait for `y/n`; Ctrl-C records a correction halt through the public application
   authority path.
6. Tests under `tests/product/` prove: scripted multi-turn loops, tool-result feedback,
   permit-denial paths, approval non-bypassability, REPL smoke via piped stdin, and an
   end-to-end "fix a failing test" task on a temporary git fixture (DeterministicProvider
   in CI; live provider verified manually and recorded).
7. Targeted and full Product tests pass; ruff clean; pyright 0 errors; wheel builds
   succeed; independent exact-diff technical review passes.

M1 exit condition: at least one real coding task completed interactively against a real
provider, with every new capability covered by failure-path tests and approval
non-bypass proven by test.

## Explicit non-goals

- M2–M4 scope: AGENTS.md auto-loading, context compression, diff-hunk edit,
  `workspace.write`, todo tool, git capability, product evals benchmark set, provider
  streaming, `rich`/`prompt_toolkit` TUI, permission modes, cost display, session
  resume, background tasks, sub-agent spawning, MCP connectors, Anthropic-native
  adapter. These are recorded design direction only and each requires its own
  authorization.
- Any new runtime dependency in M1 (stdlib only).
- Any change to `WorkflowGraph` semantics; graph execution stays the golden path / CI
  executor.
- A second event store or session storage system.
- Any domain/business semantics (Metric, SemanticObject, SQL, business actions) in
  Agent Core.
- Any autonomy, self-improvement, AGI or market-parity claim; any `R`-ledger entry.
- Broad OpenClaw-style gateways/channels, Hermes-style TUI breadth or Pi-style powerful
  shell access; the dated benchmark records why those follow evidence rather than lead
  M1.
- Push, merge, release, external publication or customer commitment.

## Stop conditions

Stop and return `REVISE_TO_SPEC` if implementation requires any of the following:

- a code path where a capability executes without `PolicyKernel.decide`, a matching
  permit or a current correction epoch;
- model output executed, shelled out or written to the workspace without becoming a
  `ProviderToolProposal` first;
- a runtime dependency added before M3;
- modifying `WorkflowGraph` or `RunCoordinator` semantics to accommodate the loop;
- session state persisted outside the existing event store;
- weakening approval, risk-tiering, `_safe_path` sandboxing, snapshot compensation or
  receipt binding to make the demo pass;
- constant-return or mock-success tests standing in for the permit, failure or
  end-to-end paths.

## Review and execution gate

This packet authorizes M1 local TDD implementation on a dedicated feature branch only.
Independent technical review of the exact implementation diff is required before any
merge request. Push, merge, release and any claim beyond `IMPLEMENTED_LOCAL` remain
separate founder gates. `docs/CURRENT_STATE.yaml` is updated (repo first, then root)
only at phase completion, with claim levels reported separately.
