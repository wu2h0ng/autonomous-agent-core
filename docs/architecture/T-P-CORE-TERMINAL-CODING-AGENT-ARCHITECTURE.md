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

## 13. M2 update (2026-09-11, rev 10) — Frozen E1/E2/E3 Execution Contracts

> Status: **REVISED_2026-09-11_REV10 / RESUBMISSION_PENDING_CTO_GATE_9 / NO_IMPLEMENTATION_AUTHORITY**
> Post-acceptance (2026-09-14): **ACCEPTED_GATE_9** — landed `df4f6ef1`; terminal line merged via PR #13 `ecc82b13`; see `docs/product/GATE9-ACCEPTANCE-TERMINAL-CODING-AGENT-M2-2026-09-14.md`. The pending marker above is retained as gate history.
> Gate history: gate 1 `REVISE_TO_SPEC` (D1 facts, D3 numbering); rev 2 corrected
> against the checkout; rev 3 adopted the reconcile finding (Wave 1 built on
> `b05d29b8`) but over-claimed it ("zero substrate change", streaming/cost ready);
> gate 2 froze the substrate truth table; gate 3 accepted facts but rejected three
> P1 execution contracts (transient-stream concurrency/loss; auto-allowance vs
> `ApprovalDecision`; self-contradictory E3 schema) → rev 5 froze all three;
> gate 4 rejected five remaining defects (E1 launch race; generation-less
> cursor; evictable gap frames; E2 tier-3/out-of-allowlist contradiction; E3
> legacy/zero scope) → rev 6 closed all five (plus the editorial removal of
> the duplicate D1 sentence in §13.3); gate 5
> `REVISE_TO_SPEC` (begin-turn stream binding; same-generation `stream_id`
> identity; READ_ONLY provenance; unbounded stall; count claim; sequencing
> ancestry) → rev 7 closed all six; gate 6 `REVISE_TO_SPEC` — two narrow
> P1: idempotency-key conflict semantics unfrozen (same key + different
> payload); stall typed-state name ambiguous (composite of two states) →
> rev 8 closed both; **gate 7 `REVISE_TO_SPEC`** — one P1 + two P2: P1
> in-flight turn concurrency model never frozen; P2 no positive E2 bypass
> assertion (constant-deny space) and stall default threshold unpinned. Rev 9
> closes all three; **gate 8 `REVISE_TO_SPEC`** — one P2 (G8-1: eight stale
> gate-7/rev-8 label residues) — rev 10 closes (label-only); E1–E3 design not
> reopened. Sequencing unchanged: after
> gate 9 the accepted packet becomes a `docs(product)` spec commit on
> `b05d29b8`, the CURRENT_STATE correction a `docs(state)` commit on top; the
> second commit's SHA is the **final M2 base**, and the
> `codex/terminal-coding-agent-m2` worktree is cut from that SHA.
> Packet: GC/CP rev 10. Sections 1–12 above describe M1; this section extends the
> brief and changes no M1 record.

**Re-scope.** §11's successor direction is amended: former M2 + M3 merge into one
M2 slice = the TUI plus three enumerated substrate extensions (E1 streaming, E2
permission modes, E3 usage honesty) on the Wave 1 base. Former M4 stays
unauthorized.

### 13.1 Substrate truth table (frozen, verified on `b05d29b8`)

- **Tier 1 — verified, adopt as-is:** session projection (`SessionProjector`,
  session_projection.py:195), durable transcripts + restart resume, durable
  deferred-approval continuation, `SurfaceRuntime` (surface_runtime.py:118),
  authenticated HTTP + resumable SSE over committed events, daemon lifecycle,
  blocking `SurfaceClient` command surface.
- **Tier 2 — primitives only:** `ProviderPort.complete_streaming`
  (provider.py:122/167/332) and the SSE parser exist, but `AgentLoop` calls the
  non-streaming `complete()` (agent_loop.py:1148); no chunk propagation; the SSE
  channel replays committed events only; `SurfaceClient` (surface_client.py:62,
  `run_turn` line 177) is blocking JSON with no incremental consumer.
- **Tier 3 — missing, M2 builds (the only authorized substrate edits): E1, E2, E3
  per the frozen contracts in §13.2.**

### 13.2 M2 frozen contracts (frozen at rev 8; unchanged through rev 10)

**E1 — streaming end-to-end, transient-stream protocol frozen (rev 8).**

- Chunks are transient display events, never durable Task events; the durable
  boundary stays turn-level.
- Separate session-stream endpoint `GET /v1/sessions/{session_id}/stream` with a
  frame-level transient cursor; the durable Task event sequence/cursor is NOT
  reused (mixed cursors produce undecidable gaps).
- **Generation binding:** every frame carries
  `(runtime_boot_id, stream_id, turn_id, frame_sequence)` and every cursor
  `(runtime_boot_id, stream_id, frame_sequence)`; `runtime_boot_id` changes on
  every daemon restart, so dead-generation sequences cannot collide. Stale-
  generation reconnect → typed `STREAM_GONE` (HTTP 410) → durable snapshot
  fallback → resubscribe.
- **Stream identity within one generation (rev 7):** a reconnect presenting a
  valid transient cursor MUST keep the original `stream_id`; a new `stream_id`
  is minted only on explicit new subscription, on stream termination, or after
  `STREAM_GONE`. Cursors of different `stream_id`s are not interchangeable.
- **Turn-start (rev 7, no launch race, no association race):**
  `SurfaceBeginTurnCommand` (reserve/begin-turn). Order: subscribe
  (`stream_id` under the current `runtime_boot_id`) → begin-turn carrying the
  statement, an **idempotency key**, and the pre-subscribed **`{runtime_boot_id,
  stream_id}`** → the server validates the stream is still live, **atomically
  binds** the turn to that stream, durably records turn-start, returns
  authoritative `{turn_id, stream_id}` → turn runs asynchronously. An invalid
  stream reference fails typed `STREAM_GONE` and the provider is never started.
  Begin-turn is the single execution trigger. Client-minted turn ids rejected;
  `turn_id` is never implementation-defined.
- **In-flight turn concurrency (rev 9):** one in-flight turn per session — a
  begin-turn arriving while a prior turn is uncommitted fails typed
  **`TURN_IN_PROGRESS`** (provider never started; no queueing, no
  multiplexing); the next turn is submitted only after the durable commit of
  the prior one.
- **Idempotency conflict semantics (rev 8):** the idempotency record binds a
  **canonical command digest** covering at least the session, the statement,
  `{runtime_boot_id, stream_id}` and the caller identity. Same key + same
  digest replays (returns the recorded ids, never re-invokes the provider);
  same key + different digest fails typed **`IDEMPOTENCY_CONFLICT`** — the
  provider is never started and the turn is never re-bound.
- Bounded per-stream buffer; overflow → explicit `gap` frames + possible
  disconnect; never silent drops. **Gap frames are synthesized on the read path
  when the consumer cursor is below the earliest retained sequence — priority
  control frames, never enqueued into the evictable buffer.**
- Completion: `stream_end` is transient; the durable commit (typed `stop_reason`)
  is authoritative; stream-end-without-commit renders "finalizing…" and resolves
  only from durable state. **Bounded stall (rev 8):** if no durable commit
  arrives within a bounded stall threshold, the TUI renders the single typed
  state **`STALLED_PENDING_DURABLE_STATE`** — a transient client state, never a
  durable Task event; never inferred completion; overruled only by the durable
  projection. The threshold is finite positive, configurable and
  test-injectable, with a fixed default of **30 seconds** (a named constant).
- Crash: transient state dies; recovery from durable projection only; in-flight
  turn shows terminated; no back-fill or fabrication.

**E2 — permission modes, durable policy allowance with provenance.**

- Protocol deltas: `SurfaceSetPermissionModeCommand`, `PermissionMode`,
  `SESSION_PERMISSION_MODE_SET` event, snapshot mode field, projector surfacing,
  operator-only issuance, policy verdict-input composition.
- Recording semantics (frozen): auto-allowance is NEVER an `ApprovalDecision`.
  Durable record for a permission-mode auto-allowed action =
  `SESSION_PERMISSION_MODE_SET` (once per change) +
  `POLICY_VERDICT_RECORDED(ALLOW, basis=permission_mode, mode_event_id=…)` +
  normal permit/receipt. Fabricated human approvals are a
  stop condition. `ApprovalDecision` stays human-only (principal/admin, exact
  digest).
- **READ_ONLY audit semantics (rev 7):** READ_ONLY auto-pass is pre-existing
  tier-default policy — NO `basis=permission_mode` record, NO `mode_event_id`.
  The three-record mode-provenance chain applies only to tier-2 in-sandbox
  policy auto-allow under `ACCEPT_IN_WORKSPACE`.
- **Decision rule (rev 6):** tier-3+ **in-allowlist** requires a human
  `ApprovalDecision` in every mode; out-of-allowlist / sandbox escape is **never
  executable** — fail-closed deny, unapprovable; no `ApprovalDecision` of any
  kind can authorize it. Every out-of-allowlist attempt (including one with an
  `ApprovalDecision(APPROVE)`) is recorded durably as
  `POLICY_VERDICT_RECORDED(DENY, basis=out_of_allowlist, reason=…)` with the
  action digest.
- Frozen matrix:

  | Capability class | ASK (default) | ACCEPT_READ_ONLY | ACCEPT_IN_WORKSPACE |
  | --- | --- | --- | --- |
  | READ_ONLY (tier-default) | auto-pass (no mode record) | auto-pass (no mode record) | auto-pass (no mode record) |
  | Tier-2 in-sandbox edit | interactive | interactive | policy auto-allow（verdict 记录 + mode 溯源） |
  | Tier-3+ in-allowlist | interactive (required) | interactive (required) | interactive (required) |
  | Out-of-allowlist / escape | fail-closed deny（不可审批） | 同左 | 同左 |

**E3 — usage/cost, frozen storage schema + legacy compatibility (rev 6, unchanged in rev 7).**

- `ProviderUsage.estimated_cost_usd: Decimal | None = None`; required
  `cost_status: KNOWN|UNKNOWN`; optional `pricing_source_ref`. Version bumps:
  usage contract `"2.0"`, surface protocol `"1.1"` (additive).
- Invariants: `UNKNOWN ⇒ None`; `KNOWN ⇒ pricing_source_ref present`; `0` is
  legal only with a trusted source (free models) — the ban is source-less zero.
  Provider writes `UNKNOWN`/`None` until a versioned price source exists.
- **Legacy (rev 6):** v1 payloads without `cost_status` decode as
  `UNKNOWN`/`None` (historical zeros projected, never rewriting raw events;
  append-only store). All in-repo producers/fixtures/readers migrate in the same
  M2 change; readers accept v1 payloads for replay indefinitely.

**TUI client (`textual`, D2 approved, UI-only).** Protocol client over the
loopback `SurfaceClient`; renders E1 frames with gap/interrupt honesty,
digest-bound approval cards, the frozen E2 matrix, tokens + `UNKNOWN` cost; holds
no governance state, opens no database.

### 13.3 Decision record (after gate 7)

- **D1 — ADOPTED.** Code baseline `b05d29b8`; final M2 base = the `docs(state)`
  correction commit SHA, preceded by the `docs(product)` spec commit carrying
  the accepted rev-10 packet (sequenced: gate 9 → spec commit → state commit →
  final SHA → clean worktree `codex/terminal-coding-agent-m2`). Adoption
  recorded at gate 2; duplicate entry removed at gate 4.
- **D2 — APPROVED.** `textual`, UI-only, pinned, automatic import-boundary test.
- **D3 — APPROVED (protocol client).** E1's incremental consumer and E2's mode
  command are the protocol deltas.
- **E1/E2/E3 — contracts frozen in rev 5, defects closed in rev 6/7/8, gate-7
  defects closed in rev 9 (in-flight concurrency, positive E2 assertion, 30s
  stall default); gate 8 closed G8-1 (label residues) in rev 10; gate 9
  verifies.**

### 13.4 M2 milestone claim table (extends §10)

| Milestone item | Primary label | Claim level now | Claim level at M2 exit |
| --- | --- | --- | --- |
| Tier 1 substrate (projection/resume/approval/runtime/protocol/daemon) | P | verified (Wave 1 heads) | verified (regression-protected) |
| E1 streaming end-to-end (transient envelope + stream protocol + begin-turn + generation binding) | P | specified | tested + live e2e |
| E2 permission modes (protocol/policy/projection; provenance recording) | A/P | specified | verified (matrix + no-fabricated-approval tests) |
| E3 usage schema (None/UNKNOWN/KNOWN + tokens; v1 legacy decode) | P | specified | tested (no source-less zero; KNOWN+0 with source legal) |
| TUI client | P/U | specified | integrated (live e2e record) |
| D2 import-boundary test | E | specified | verified |
| Wave 1 + M1 regression suites | E | verified | verified (green with E1–E3 tests) |
| Compression / AGENTS.md / indexing / checkpoint; price table | P | recorded direction | out of scope (M2) |
| Sub-agents / MCP / background tasks | P | recorded direction | out of scope (M4 lineage) |
| Research / autonomy claims | R | none | none |

### 13.5 M2 rejected designs

1. **TUI owning session or governance state** — rejected: second writer to the
   event store.
2. **Any mode bypassing `PolicyKernel.decide`** — rejected: C7 non-writable.
3. **Durable per-chunk Task events** — rejected: transient display events only;
   the event store keeps turn-level durability.
4. **A session/message table beside the event store** — rejected per §2 design 2.
5. **Substrate edits beyond E1–E3** — rejected: whitelist with exact-diff review.
6. **Source-less cost zero for real calls** — rejected: `UNKNOWN` only; a
   trusted-source `KNOWN`+`0` (genuinely free models) is legal.
7. **Rebuilding Wave 1 components the TUI needs** — rejected: extend E1–E3
   narrowly; adopt the rest.
8. **Reusing the durable event sequence/cursor as the stream cursor** — rejected
   at gate 3; independent transient cursor only.
9. **Recording policy auto-allowance as `ApprovalDecision`** — rejected at gate 3;
   `POLICY_VERDICT_RECORDED(basis=permission_mode, mode_event_id)` is the only
   durable allowance record; human `ApprovalDecision` never fabricated.
10. **TUI-side cost masking over stored pseudo-precise zeros** — rejected at
    gate 3; the schema change removes zero at the source.
11. **Client-minted turn ids / implementation-defined `turn_id`** — rejected at
    gate 4; `SurfaceBeginTurnCommand` round-trip is the only source.
12. **Enqueuing gap frames into the evictable stream buffer** — rejected at
    gate 4; gaps are read-path synthesized priority control frames.
13. **Approving out-of-allowlist / sandbox-escape actions** — rejected at gate 4;
    they are unapprovable fail-closed denies in every mode.
14. **Bare integer stream cursors without generation binding** — rejected at
    gate 4; cursors carry `runtime_boot_id` and stale generations fail typed
    `STREAM_GONE` (410).
15. **Rewriting historical usage events to the v2 schema** — rejected at gate 4;
    the store is append-only; v1 payloads decode as UNKNOWN+None at read time.
16. **Begin-turn without stream binding** — rejected at gate 5; the command
    carries the pre-subscribed `{runtime_boot_id, stream_id}`, the server
    validates the stream and atomically binds, invalid → typed `STREAM_GONE`,
    provider never started.
17. **Minting a new `stream_id` on same-generation reconnect, or interchangeable
    cursors across streams** — rejected at gate 5; valid-cursor reconnect keeps
    the original `stream_id`.
18. **Recording READ_ONLY auto-pass with `basis=permission_mode`** — rejected at
    gate 5; READ_ONLY is tier-default policy with no mode-provenance record.
19. **Inferring completion from a stall timeout** — rejected at gate 5; the TUI
    renders only typed `STALLED_PENDING_DURABLE_STATE` and the
    durable projection stays authoritative.
20. **Landing the state correction without the accepted spec as an ancestor of
    the final base** — rejected at gate 5; the `docs(product)` spec commit
    precedes the `docs(state)` commit.
21. **Replaying an idempotency key with a different command payload** — rejected
    at gate 6; the idempotency record binds a canonical command digest
    (session, statement, stream binding, caller identity); same key + different
    digest fails typed `IDEMPOTENCY_CONFLICT`, provider never started.
22. **A composite/ambiguous stall state name, or persisting stall as a durable
    event** — rejected at gate 6; the single typed value is
    `STALLED_PENDING_DURABLE_STATE`, transient only, threshold configurable and
    test-injectable with a fixed 30-second default.
23. **Queueing or multiplexing a second in-flight turn on a session** —
    rejected at gate 7; one in-flight turn per session — a second begin-turn
    fails typed `TURN_IN_PROGRESS` with no provider start.

### 13.6 M2 verification boundary

Pre-implementation ceiling: `SPECIFIED_ONLY` (Tier 1 rows excepted — they carry
Wave 1's recorded verified heads and must not be re-claimed). M2 exit requires:
Wave 1 + M1 suites green with E1–E3 extension tests; bypass set covering stream
lifecycle (subscribe-first; begin-turn stream binding + idempotency — unbound or
invalid-stream begin-turn fails typed `STREAM_GONE` with no provider start;
same key + same digest replays without provider re-invocation, same key +
different digest fails typed `IDEMPOTENCY_CONFLICT`; a begin-turn during an
uncommitted prior turn fails typed `TURN_IN_PROGRESS` with no provider start,
no queueing, no multiplexing; generation-bound
frames/cursors with typed 410 fallback; same-generation `stream_id` stability
with non-interchangeable cursors; read-path gap synthesis with non-evictable
gap frames; no finalize-without-commit; bounded stall renders only the single
typed `STALLED_PENDING_DURABLE_STATE` (transient, never durable; threshold
test-injectable with a fixed 30-second default); crash honesty), E2 provenance (no
fabricated `ApprovalDecision`, valid `mode_event_id` chain for permission-mode
auto-allowance only, a positive `ACCEPT_IN_WORKSPACE` tier-2 auto-allow path
with the three-record chain present and resolvable — a constant-deny
implementation must fail, READ_ONLY auto-pass carrying no mode-provenance record,
matrix no-bypass, out-of-allowlist never executed even with an approval
present), E3 schema
invariants (UNKNOWN⇒None, KNOWN⇒value+source, no source-less zero, v1 payload
replay decode, raw events never rewritten); headless TUI tests (textual pilot);
one recorded live-provider TUI session; D2 boundary test; ruff/pyright/wheels;
independent exact-diff review including the substrate-diff whitelist. Not
established by M2: push, merge, release, production readiness, sub-agents/MCP,
price/cost recovery, any autonomy or market-parity claim.
