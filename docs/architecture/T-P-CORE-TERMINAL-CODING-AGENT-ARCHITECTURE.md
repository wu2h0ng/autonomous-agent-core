# T-P-CORE-TERMINAL-CODING-AGENT Architecture Brief — Governed Multi-Turn Agent Loop (M0 + M1)

> Date: 2026-07-26
> Status: **SPEC_APPROVED / M1_LOCAL_TDD_IMPLEMENTATION_AUTHORIZED / NO_RELEASE_AUTHORITY**
> Track: Product
> Base: `27337578e15f307bec18edb5221356d5c3ed6c04`
> Goal Card: `docs/product/GC-TERMINAL-CODING-AGENT-M0-M1-2026-07-26.md`
> Context Pack: `docs/product/CP-TERMINAL-CODING-AGENT-M0-M1-2026-07-26.md`
> Dated benchmark: `docs/product/TERMINAL-AGENT-CLI-BENCHMARK-2026-07-26.md`

## 1. Decision

Add a new execution form — a governed multi-turn conversation loop — beside the
existing static graph executor, and expose it through a stdlib terminal REPL. Four
core decisions:

1. **New `agent_loop` module; `WorkflowGraph` semantics unchanged.** Multi-turn
   dialogue is a new execution form, not a graph extension. Graph execution remains the
   golden-path / CI executor.
2. **The Task/Run stream is the M1 audit spine, not yet a resumable conversation
   store.** Turn metadata, provider responses/receipts and action governance reuse the
   existing event store / SQLite. Live provider-message history remains in memory.
   Full message replay, session resume and branching are M2; no second storage system
   is created in M1.
3. **Tools are capabilities.** Every terminal tool is a `WorkspaceSandbox` capability
   (or a new `CapabilityPort` connector), inheriting permit, audit and compensation.
   Risk tiering: read/search-class capabilities are READ_ONLY and auto-pass policy;
   edit/shell-class capabilities require a policy verdict, which interactive mode maps
   to a terminal confirmation on the existing approval path.
4. **Dependency discipline.** M1 adds zero runtime dependencies (stdlib REPL). M3 may
   introduce `rich`/`prompt_toolkit` as UI-only dependencies.

```text
operator input (REPL / run -p)
        |
        v
AgentLoop.run_turn(session_id, user_input)
        |
        v
context assembly (system prompt + live session history, simple truncation)
        |
        v
ProviderPort.complete()  --->  assistant text + ProviderToolProposal[]
        |                            |
        |                            | (model output is only ever proposals)
        |                            v
        |               per proposal: PolicyKernel.decide
        |                            -> ActionPermit (exact action)
        |                            -> correction-epoch check
        |                            -> CapabilityBroker.invoke
        |                            -> result as TOOL message
        |                            |
        +<---------------------------+
        |   (repeat until no proposal,
        |    turn cap, token budget,
        |    retry exhaustion or
        |    repeated-digest stop)
        v
TurnResult; every step appended as events + ProviderExecutionReceipt
```

## 2. Rejected designs

1. **Extend `WorkflowGraph` / `RunCoordinator` with conversational cycles** — rejected
   because it mutates a validated static-graph executor to serve a different execution
   form, blurring the golden path; a separate module keeps both forms auditable.
2. **A dedicated session store** — rejected because a second persistence system would
   duplicate durability, correction and audit semantics that the event store already
   provides.
3. **Direct tool dispatch from parsed model output** — rejected because it bypasses
   `PolicyKernel.decide` / permit / epoch (C7). All dispatch goes through the broker.
4. **Auto-approving edit/shell actions in interactive mode** — rejected because
   interactivity is not a permission class; the verdict requirement is preserved and
   surfaced as a terminal confirmation.
5. **Whole-file `apply_patch` as the only edit tool** — rejected for M1 practicality
   (token cost); `workspace.edit` adds exact string replacement with uniqueness check
   while keeping the same snapshot-compensation mechanism.
6. **Early TUI/streaming dependencies** — rejected for M1 because they add dependency
   and review surface without changing the governed-loop claim; deferred to M3.

## 3. Contract extensions

`packages/contracts/src/agent_os_contracts/provider.py`:

- `ProviderMessage` gains optional `tool_call_id` and `tool_calls` fields: TOOL-role
  messages bind a result to its originating call; ASSISTANT messages echo the calls the
  provider made. Both are required for correct multi-turn serialization.
- New typed contracts `SessionRef` and `TurnId` (session/turn identity), and
  `TurnResult` as the loop's typed output.

Contracts remain closed (`extra="forbid"` style, matching existing `ContractModel`
conventions): no caller- or model-supplied verdict, permit, epoch or storage field.

`packages/os_core/src/agent_os_core/provider.py`:

- `OpenAICompatibleProvider._invoke` serializes TOOL messages (`tool_call_id`) and
  ASSISTANT `tool_calls`; response parsing is unchanged.
- `DeterministicProvider` supports scripted multi-turn response sequences for hermetic
  tests.

## 4. AgentLoop

New file `packages/os_core/src/agent_os_core/agent_loop.py`:

```python
class AgentLoop:
    def __init__(self, provider, policy, broker, correction, tasks, config): ...
    def run_turn(self, session_id: SessionRef, user_input: str) -> TurnResult: ...
```

Behavior:

- the cycle in §1 runs until the provider returns no tool proposal, or a stop
  condition fires: turn cap, token budget cap, retryable provider-failure exhaustion
  (retryable status codes only), or loop detection (the same proposal digest repeating
  N times halts the turn);
- each successful provider call appends a typed response plus
  `ProviderExecutionReceipt`; receipt construction is extracted from
  `proposal_engine.py` into a shared helper rather than duplicated;
- context assembly is the fixed system prompt plus live session history with a simple
  truncation strategy; `AGENTS.md` discovery, replay and compression are M2 scope.

The loop holds no authority of its own: it cannot mint permits, skip verdicts, write
events outside the store, or invoke a capability directly.

## 5. New capabilities (all inside `WorkspaceSandbox`, all through `_safe_path`)

- `workspace.edit` — exact string replacement (`old_string`/`new_string`) with
  uniqueness validation and the existing snapshot-compensation mechanism; cheaper in
  tokens than whole-file `apply_patch`.
- `workspace.search` — glob/grep/ls via stdlib `fnmatch` + line regex; truncated
  output; READ_ONLY tier.
- `workspace.shell` — exact configured command allowlist + tier-3 approval, timeout,
  output truncation, artifact capture and a minimal subprocess environment that omits
  provider credentials. M1 does not expose arbitrary shell commands and does not claim
  OS filesystem/network isolation.

Each capability is spec-registered, has explicit failure paths (illegal path, expired
permit, epoch drift) and is introduced by a failing / bypass-detecting test first.
Capabilities stay generic workspace primitives — no coding-business semantics enter
Agent Core.

## 6. CLI entry point (`apps/cli/__main__.py`)

- `chat` subcommand: stdlib `input()` REPL; prints assistant text and tool-call
  summaries per turn; `/exit`, `/status`; Ctrl-C maps to a correction halt recorded in
  the event stream, not an unrecorded kill.
- `chat -p "..."`: non-interactive single-prompt mode; any edit/shell action fails
  closed because no human confirmation surface exists.
- Approval bridge: an action whose verdict requires approval renders the diff/command
  in the REPL and waits for `y/n`; for tier 3, `y` becomes an exact-action,
  digest-bound `ApprovalDecision` consumed by `PolicyKernel`. Tier-2 edits also require
  terminal confirmation even though the kernel risk rule does not independently
  require an approval object. The REPL is a confirmation surface, not a permission
  override.

## 7. Authority invariants (red lines, checked at every phase review)

- No code path bypasses `PolicyKernel.decide`, the exact-action `ActionPermit`, or
  correction-epoch validation (C7 non-bypassable).
- Model output produces `ProviderToolProposal` only; it never executes, never writes
  the workspace directly and never becomes an untyped consequential command.
- Agent Core contains no business/domain semantics; the new capabilities are
  domain-independent.
- One event store; one policy kernel; one broker. The loop adds no parallel authority
  spine.
- Claim discipline: `specified / implemented / tested / integrated / verified`
  reported separately; `docs/CURRENT_STATE.yaml` updated at phase completion (repo
  first, then root).

## 8. Failure semantics

- invalid or unsafe path: capability failure before any write, recorded as an event;
- expired/mismatched permit or epoch drift: invocation refused, recorded;
- provider failure: retryable codes retried within budget, otherwise the turn ends and
  `SESSION_TURN_COMPLETED.stop_reason` records the typed failure code; durable failed
  provider-attempt receipts are not claimed in M1;
- approval declined (`n`): proposal recorded as denied, loop continues without the
  effect;
- repeated identical proposals: deterministic halt, recorded (anti-loop);
- operator interrupt: correction halt event; session remains resumable in principle
  (resume itself is M4 scope).

## 9. Engineering reality review (root constitution §14)

- **Entry point:** `python -m apps.cli chat` and `python -m apps.cli chat -p`, calling
  `AgentLoop.run_turn()`; no other consumer is claimed for M1.
- **Contract:** `ProviderMessage` (+`tool_call_id`/`tool_calls`), `SessionRef`,
  `TurnId`, `TurnResult`, capability specs for `workspace.edit` / `workspace.search` /
  `workspace.shell`.
- **Failure:** §8 paths, each covered by a dedicated test.
- **Test validity:** tests fail if the loop returns constant success, skips
  `PolicyKernel.decide`, invokes without a permit, ignores epoch drift, or if approval
  can be bypassed; DeterministicProvider scripts assert exact call sequences, not just
  final state.
- **Integration:** the loop consumes the real provider port, policy kernel, broker,
  correction authority and event store — the same instances the rest of the product
  uses; the CLI composes them through the existing composition path.
- **Observability:** Task/Run audit stream plus `ProviderExecutionReceipt` per
  successful provider call; `/status` currently renders identifiers and the in-memory
  history count. Durable message replay/resume is not established.
- **Claim class:** product-runtime evidence only. Not research evidence, not process
  evidence, not commercial evidence; no autonomy or market-parity claim.

## 10. Milestone taxonomy and claim levels (root constitution §9A)

| Milestone item | Primary label | Claim level now | Claim level at M1 exit |
| --- | --- | --- | --- |
| M0 governance packet (this document set) | E | specified | verified (CTO gate) |
| U: terminal coding assistance outcome | U | specified | verified (live e2e record) |
| Contract extensions (`ProviderMessage`, `SessionRef`, `TurnId`, `TurnResult`) | P | specified | tested |
| Provider serialization + scripted DeterministicProvider | P | specified | tested |
| `workspace.edit` / `workspace.search` / `workspace.shell` capabilities | P | specified | tested |
| `AgentLoop` governed multi-turn loop | P | specified | integrated |
| CLI REPL + approval bridge + Ctrl-C halt | P | specified | integrated |
| C7 / permit / epoch / proposal-only invariants | A | specified | verified (bypass tests) |
| Targeted + Product suite, ruff, pyright, wheels, review | E | specified | verified |
| Research / autonomy claims | R | none | none (out of scope) |

`E` items close only `E`; no `E` result closes the `P` or `U` rows.

## 11. Successor design direction (not authorized)

- M2: Pi-like session replay/resume/branch and JSON/RPC surfaces; hierarchical
  `AGENTS.md` auto-load with change digests; deterministic context compression (itself
  event-recorded); structured trusted-project command profiles; read-first git
  status/diff; coding-task product eval set.
- M3: provider streaming (`complete_stream`, SSE, per-chunk events),
  Hermes-like observable TUI/steering, `--permission-mode` mapped to verdict inputs
  (never a hardcoded bypass), live token/cost display and explicit process-isolation
  modes.
- M4: background tasks, `agent.spawn` sub-agents (scope ≤ parent, single-writer
  discipline), MCP client connector (tools wrapped as typed capabilities through the
  same permit pipeline), Anthropic-native protocol adapter. OpenClaw-style
  gateway/channel breadth remains later and evidence-gated.

Each successor requires its own Goal Card / gate before implementation.

## 12. Verification boundary

M1 evidence ceiling before a real-provider run and review is
`IMPLEMENTED_LOCAL / TARGETED_TESTED / STUB_PROVIDER_E2E / NOT_REVIEWED`. Not
established by this package: live-provider verification, production readiness,
sustained multi-task reliability, parity with Hermes/OpenClaw/Pi/Claude Code/Codex
CLI, any autonomy property, security certification, migration, push, merge or release.
