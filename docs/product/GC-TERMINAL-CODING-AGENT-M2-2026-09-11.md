# Terminal Coding Agent Goal Card — Rich TUI + Streaming + Permission Modes (M2, rev 10)

> Date: 2026-09-11 (revision 10, after CTO gate 8 `REVISE_TO_SPEC`)
> Track: Product
> Status: **REVISED_2026-09-11_REV10 / RESUBMISSION_PENDING_CTO_GATE_9 / NO_IMPLEMENTATION_AUTHORITY / NO_RELEASE_AUTHORITY**
> Gate history: gate 1 (facts, numbering) → rev 2; reconcile finding → rev 3;
> gate 2 (substrate truth: streaming unwired, no mode surface, fake cost) → rev 4;
> gate 3 (three P1 execution-contract ambiguities) → rev 5 froze all three;
> gate 4 `REVISE_TO_SPEC` (five gaps: turn_id source, generation-less cursor,
> evictable gap frames, E2 tier-3/out-of-allowlist contradiction, E3 legacy/zero
> scope) → rev 6 closed all five; gate 5 `REVISE_TO_SPEC` (stream binding,
> same-generation reconnect identity, READ_ONLY provenance, unbounded stall,
> rejected-designs count, sequencing ancestry) → rev 7 closed all six; gate 6
> `REVISE_TO_SPEC` — two narrow P1 — idempotency-key conflict semantics
> unfrozen (same key + different payload); stall typed-state name ambiguous
> (composite of two states) → rev 8 closed both without reopening the E1–E3
> design; **gate 7 `REVISE_TO_SPEC` — one P1 + two P2** — P1: in-flight turn
> concurrency model never frozen (a second begin-turn on an uncommitted turn
> had no defined semantics); P2: no positive E2 bypass assertion (constant-deny
> space); stall default threshold value unpinned. Rev 9 closes all three.
> **gate 8 `REVISE_TO_SPEC` — one P2 (G8-1): eight stale gate-7/rev-8 label
> residues** — rev 10 closes (label-only; no contract, matrix, threshold, or
> sequencing change). No commit, no worktree, no implementation.
> Base sequencing (re-frozen at gate 5, unchanged by rev 10):
> 1. Gate 9 accepts rev 10 (this packet).
> 2. In a temporary clean worktree of `b05d29b8`: land the accepted rev-10 packet
>    (GC/CP/AB §13) as an independent `docs(product)` spec commit.
> 3. Land the CURRENT_STATE correction as a `docs(state)` commit on top — exact
>    text in Context Pack §Companion state correction.
> 4. The second commit's SHA is the **final M2 exact base** (code baseline
>    `b05d29b8` + accepted spec + state correction).
> 5. Create the clean D1-step-2 worktree from that SHA; cut branch
>    `codex/terminal-coding-agent-m2`.
> Claim ceiling before implementation review: `SPECIFIED_ONLY`
> Authority: founder request 2026-09-11 ("需要具有市面 agent 的核心能力和富 TUI")
> Predecessor packet: `docs/product/GC-TERMINAL-CODING-AGENT-M0-M1-2026-07-26.md`
> Architecture lineage: `docs/architecture/T-P-CORE-TERMINAL-CODING-AGENT-ARCHITECTURE.md` §11, §13
> Substrate references: Wave 1 plan + `.agent_runs/native-surface-wave1-20260811/verification.md`
> UI design baseline: `docs/product/AGENT-SURFACE-UI-BENCHMARK-2026-08-15.md`
> Dated benchmark: `docs/product/TERMINAL-AGENT-CLI-BENCHMARK-2026-07-26.md`
> D1 reconcile: `D1-RECONCILE-b05d29b8-2026-09-11.md` (workspace root)

## Goal

Deliver the terminal operator surface of the Agent OS coding agent: a rich TUI
(`textual`, D2-approved) as a **protocol client**, with **end-to-end streaming**
(E1, with a frozen concurrency/loss protocol), **permission modes** (E2, recorded
as durable policy allowance with provenance — never fabricated approvals), and
**honest token/cost visibility** (E3, with a frozen storage schema) — while every
authority invariant stays exactly as strong as today.

The user-facing outcome (`U`): an operator opens `agent-os chat`, gets the TUI,
watches streamed output with explicit gap/interrupt honesty, approves/rejects
in place, steers with permission modes, sees accurate tokens and `UNKNOWN` cost,
and resumes across restarts.

The product capability (`P`): substrate extensions E1–E3 (enumerated, whitelisted),
the TUI client, and their integration/verification.

## Substrate truth table (unchanged from rev 4, restated for binding)

- **Tier 1 — verified, adopt as-is:** session projection, durable transcripts,
  restart resume, durable deferred-approval continuation, `SurfaceRuntime`,
  authenticated HTTP + resumable SSE over committed events, daemon lifecycle,
  blocking `SurfaceClient` commands.
- **Tier 2 — primitives only:** `complete_streaming` + SSE parser exist; the loop
  still calls non-streaming `complete()`; `SurfaceClient` is blocking JSON; SSE
  replays committed events only.
- **Tier 3 — missing, M2 builds (only authorized substrate edits): E1, E2, E3.**

## E1 — end-to-end streaming, with frozen transient-stream protocol (rev 8)

**Event classification (frozen):** chunks are transient display events, never
durable Task events. The durable boundary stays turn-level; resume re-renders
from durable content.

**Stream channel (frozen):** a **separate session-stream endpoint with its own
transient cursor** — `GET /v1/sessions/{session_id}/stream` with frame-level
`Last-Event-ID`. It MUST NOT reuse the durable Task event sequence or its cursor:
mixing the two cursors produces undecidable gaps. Every frame is bound to
**`(runtime_boot_id, stream_id, turn_id, frame_sequence)`**; every cursor is
`(runtime_boot_id, stream_id, frame_sequence)`: `runtime_boot_id`
identifies the daemon process generation and changes on every restart, so a dead
generation's sequence can never collide with the new one. A client that
reconnects presenting a stale generation receives the typed `STREAM_GONE` error
(HTTP 410 + typed body) and falls back to the durable snapshot, then resubscribes
(new stream under the new generation).

**Stream identity within one generation (frozen):** within one daemon
generation, a reconnect presenting a valid transient cursor MUST keep the
original `stream_id`; a new `stream_id` is minted only on explicit new
subscription, on stream termination, or after `STREAM_GONE`. Cursors of
different `stream_id`s are not interchangeable.

**Turn-start (frozen — no launch race, no association race):** the protocol
gains `SurfaceBeginTurnCommand` (reserve/begin-turn). Order of operations:

1. The TUI establishes the stream subscription **first** (receives `stream_id`
   under the current `runtime_boot_id`).
2. The TUI issues `SurfaceBeginTurnCommand` carrying the statement, an
   **idempotency key**, and the pre-subscribed **`{runtime_boot_id,
   stream_id}`**. The server validates that the referenced stream is still
   live, **atomically binds** the turn to that stream, durably records
   turn-start, and returns the authoritative `{turn_id, stream_id}`. If the
   referenced stream is no longer valid, the command fails typed
   `STREAM_GONE` and **the provider is never started**.
3. The turn then executes **asynchronously**; every frame binds to both ids.

Begin-turn is the single execution trigger; there is no separate
unauthenticated execute path. **Idempotency conflict semantics (frozen,
rev 8):** the idempotency record binds a **canonical command digest** covering
at least the session, the statement, `{runtime_boot_id, stream_id}` and the
caller identity. The same key with the **same** digest replays — it returns
the already-recorded `{turn_id, stream_id}` and **never re-invokes the
provider**. The same key with a **different** digest fails typed
**`IDEMPOTENCY_CONFLICT`**: the provider is never started and the turn is never
re-bound.

**In-flight turn concurrency (frozen, rev 9):** one in-flight turn per
session. A `SurfaceBeginTurnCommand` arriving while a prior turn is
uncommitted fails typed **`TURN_IN_PROGRESS`** — the provider is never
started, and no second turn is queued, multiplexed, or bound. The TUI
submits the next turn only after the durable commit of the prior one.

The client never mints turn ids, and `turn_id` is never "decided at
implementation time" — the begin-turn round-trip is the only source. (The
alternative, client-generated `client_turn_id` mapped server-side, was
considered and rejected: it shifts idempotency and digest-binding burden onto
clients and forks the identity model.)

**Buffer, gap and consumer policy (frozen):**

- **Bounded buffer per session-stream.** When the buffer watermark is exceeded
  the server may disconnect the slow consumer; it never silently drops frames.
- **Gap frames are synthesized on the read path, never enqueued.** Whenever a
  consumer's cursor is below the earliest retained sequence, the server emits an
  explicit `gap` control frame (`gap_from/gap_to`) ahead of live frames. Gap
  frames are priority control frames, not buffer residents, so they cannot
  themselves be evicted by overflow.
- **Disconnect/reconnect:** the client reconnects with its last
  `(runtime_boot_id, stream_id, frame_sequence)` cursor; missed ranges render as
  explicit gaps, never as fabricated content. If the durable turn has already
  committed, the client may re-render the final turn from the durable snapshot.

**Completion ordering (frozen):** `stream_end` (transient) means the provider
stream closed; the **durable turn commit is authoritative** — the TUI finalizes
turn rendering only when the durable snapshot carries the turn's typed
`stop_reason`. A stream that ends without a durable commit renders
"finalizing…"; it resolves to `completed` or `interrupted` solely from the
durable record. **Bounded stall (rev 8):** if no durable commit arrives within
a bounded stall threshold, the TUI renders the single typed state
**`STALLED_PENDING_DURABLE_STATE`**. It is a transient client state — never a
durable Task event; recovery, completion or interruption is only ever
overridden from the durable projection, and the TUI never infers completion
from the timeout. The stall threshold is a finite positive value, configurable
and test-injectable, with a fixed default of **30 seconds** (a named constant).

**Daemon crash (frozen):** transient state dies with the process; the new
generation has a new `runtime_boot_id`, so stale cursors fail typed (`STREAM_GONE`
/ 410). Recovery comes only from durable session state (projection): a turn in
flight shows as terminated and the session resumes at the last durable boundary.
No frames are ever back-filled or fabricated.

**Work items:** `AgentLoop` streaming path via `complete_streaming` (committed
message/receipt semantics unchanged); typed transient frame contracts incl.
`SurfaceBeginTurnCommand`; runtime/route pass-through without storage;
`SurfaceClient` incremental SSE consumer implementing the lifecycle above.

## E2 — permission modes, recorded as durable policy allowance with provenance

**Protocol extension (enumerated):** closed-contract
`SurfaceSetPermissionModeCommand` + `PermissionMode` literal +
`SESSION_PERMISSION_MODE_SET` durable event + snapshot mode field; runtime
enforces operator-only issuance; policy translates mode into verdict inputs
composing the existing gateway family; projector surfaces mode.

**Recording semantics (frozen):** an auto-allowed action is NEVER recorded as
`ApprovalDecision(APPROVE)`. `ApprovalDecision` expresses a principal/admin human
approving an exact digest; a permission mode is prior session policy, not
per-action human approval. The durable record for a permission-mode
auto-allowed action is exactly:

1. `SESSION_PERMISSION_MODE_SET` — who set the mode, when, prior digest (once per
   change);
2. `POLICY_VERDICT_RECORDED` — verdict `ALLOW`, `basis=permission_mode`,
   `mode_event_id` referencing (1), plus capability id, tier and action digest;
3. the normal `ActionPermit` + action receipt.

**READ_ONLY audit semantics (frozen):** READ_ONLY auto-pass is the
pre-existing tier-default policy. It produces NO `basis=permission_mode` record
and NO `mode_event_id`; the three-record mode-provenance chain above applies
only to tier-2 in-sandbox policy auto-allow under `ACCEPT_IN_WORKSPACE`.

Tier-3+ **in-allowlist** actions require a real human `ApprovalDecision` in every
mode. Out-of-allowlist / sandbox-escape actions are **never executable**:
fail-closed deny, not approvable — no `ApprovalDecision`, human or otherwise,
can authorize them. Every out-of-allowlist attempt — including one accompanied
by an `ApprovalDecision(APPROVE)` — is denied, and the denial is recorded
durably as `POLICY_VERDICT_RECORDED(DENY, basis=out_of_allowlist, reason=…)`
with the action digest. Fabricating a durable `ApprovalDecision` with
`actor_id=user` for an auto-allowed action is a stop condition.

**Frozen mode × tier × verdict matrix:**

| Capability class | ASK (default) | ACCEPT_READ_ONLY | ACCEPT_IN_WORKSPACE |
| --- | --- | --- | --- |
| READ_ONLY (tier-default) | auto-pass (no mode record) | auto-pass (no mode record) | auto-pass (no mode record) |
| Tier-2 in-sandbox edit (`workspace.edit` 类) | interactive approval | interactive approval | **policy auto-allow**（记录 1–3：mode 事件 + verdict 记录 + permit/receipt） |
| Tier-3+ in-allowlist (`workspace.shell` 等) | interactive approval (required) | interactive approval (required) | interactive approval (required) |
| Out-of-allowlist / sandbox escape | fail-closed deny（**不可审批**，任何 ApprovalDecision 均无效） | 同左 | 同左 |

## E3 — usage/cost, with frozen storage schema and legacy compatibility (rev 6, unchanged)

**Frozen schema decision:** `ProviderUsage` changes to
`estimated_cost_usd: Decimal | None = None`, plus required
`cost_status: Literal["KNOWN", "UNKNOWN"]`, plus optional `pricing_source_ref`.
Contract schema versions are bumped with this change: the usage contract to
`"2.0"`, the surface protocol to `"1.1"` (additive minor). Invariants:
`UNKNOWN ⇒ estimated_cost_usd is None`; `KNOWN ⇒ pricing_source_ref present`
(the value may be `0` **only with** a trusted `pricing_source_ref` — genuinely
free models are legal; the ban is on **source-less zero**, not on zero itself).
The OpenAI-compatible provider sets `cost_status="UNKNOWN"` and `None` until a
versioned price source exists; it never writes a source-less zero for real calls.
TUI-side masking alone is insufficient — the storage layer must stop producing
pseudo-precise zeros.

**Legacy compatibility (frozen):** historical payloads without `cost_status`
(usage v1) decode as `cost_status="UNKNOWN"`, `estimated_cost_usd=None` —
including historical zeros, which are **projected** as UNKNOWN+None at read/
projection time. Raw historical events are **never rewritten**; the event store
is append-only. Compatibility window: all in-repo producers, fixtures and
event/receipt readers migrate in the same M2 change, and readers must continue
accepting v1 payloads for event replay indefinitely (no external consumers
exist today).

## In-scope (P0 — authorized only after gate 9 + base sequencing)

1. **E1** per the frozen protocol above.
2. **E2** per the frozen recording semantics and matrix above.
3. **E3** per the frozen schema above.
4. **TUI client (`textual`, UI-only, pinned).** Renders E1 frames with gap/
   interrupt honesty; digest-bound approval card; mode switcher rendering the
   frozen matrix; tokens + `UNKNOWN` cost; status surface; Ctrl-C → correction
   halt as first-class state; slash set `/exit /status /resume /cost /mode`.
5. **Integration + verification** per the done conditions.

## Recorded direction, not authorized (P1+)

Durable per-chunk archival; versioned price table / billing recovery; context
compression; AGENTS.md auto-load; codebase indexing; checkpoint/rollback;
`workspace.write`/diff-hunk edit; todo tool; git capabilities; product eval set;
background tasks; sub-agents; MCP; Anthropic adapter; multi-workspace daemon
hosting; Web/desktop surfaces (Wave 2 Tauri separate).

## Allowed inputs / outputs

**Allowed inputs:** operator text, slash commands, approval decisions,
permission-mode changes (operator-only), governed workspace root, provider
credentials via the existing environment path.

The model may not supply its own permit, verdict, epoch, approval, permission
mode or storage write. The TUI may not inject messages, tool results or receipts
outside the typed protocol path.

**Outputs:** durable Task/session events via the existing store (no second
storage system; no durable chunk events); workspace effects only through
brokered capabilities with snapshot compensation; TUI rendering derived from
frames/events/receipts.

## Authority and identity condition

- Composition root and authority spine unchanged. TUI is a renderer/input
  surface only.
- E1: turn atomicity unchanged; transient frames are display state; post-crash
  recovery reads only durable state.
- E2: C7 non-writable; modes are verdict inputs; auto-allowance is recorded as
  policy verdict with provenance, never as human approval; mode changes are
  operator-only and event-recorded.
- E3: `UNKNOWN` is the only non-priced state; source-less zero is banned as
  display and stored data; zero is legal only under `KNOWN` with a trusted
  `pricing_source_ref`.
- Ctrl-C / timeout map to existing correction semantics; never an unrecorded
  kill.

## Done conditions

M2 may be called locally implemented only after all of the following:

1. Gate 8 accepts this packet; base sequencing executed (`docs(product)` spec
   commit + `docs(state)` correction commit landed; final base = the second
   commit's SHA; D1-step-2 worktree `codex/terminal-coding-agent-m2` created
   from it).
2. Test-first for every change (AGENTS.md §4), minimum bypass set:
   - E1: begin-turn is the only source of `turn_id` (client-minted ids
     rejected); begin-turn MUST carry the pre-subscribed `{runtime_boot_id,
     stream_id}` and the server rejects an invalid stream with typed
     `STREAM_GONE` without starting the provider; a duplicate begin-turn with
     the same idempotency key AND the same canonical command digest never
     re-invokes the provider; the same key with a DIFFERENT digest fails typed
     `IDEMPOTENCY_CONFLICT` (no provider start, no re-bind); a begin-turn
     while a prior turn is uncommitted fails typed `TURN_IN_PROGRESS` (no
     provider start, no queueing, no multiplexing); subscription
     precedes execution; frames bound to `{runtime_boot_id,
     stream_id, turn_id, frame_sequence}`; a stale-generation cursor yields
     typed `STREAM_GONE` (410) with durable-snapshot fallback — never
     cross-generation frame splicing; within one generation a valid-cursor
     reconnect keeps the original `stream_id` and cursors of different
     `stream_id`s are rejected as interchangeable; buffer overflow never
     silently loses frames; `gap` frames are synthesized on the read path
     ahead of retained frames (never enqueued, never evicted); `stream_end`
     without durable commit never finalizes; stall timeout renders only the
     single typed `STALLED_PENDING_DURABLE_STATE` (transient, never a durable
     event, never inferred completion; threshold configurable and
     test-injectable with a fixed 30-second default); daemon-crash recovery
     renders terminated from durable state only;
   - E2: no mode auto-approves tier-3+/out-of-allowlist; out-of-allowlist is
     unapprovable — an `ApprovalDecision(APPROVE)` for it never executes and a
     durable DENY verdict with reason is recorded; the model cannot set a
     mode; under `ACCEPT_IN_WORKSPACE` a tier-2 in-sandbox action **is**
     policy auto-allowed (positive path — a constant-deny implementation must
     fail this test) with the three-record chain (mode event + verdict +
     permit/receipt) present and `mode_event_id` resolvable; every
     **permission-mode** auto-allowed action has
     `POLICY_VERDICT_RECORDED` with valid `mode_event_id` chain; **no
     `ApprovalDecision` exists for any auto-allowed action**; READ_ONLY
     auto-pass produces no `basis=permission_mode` record and no
     `mode_event_id`;
   - E3: `UNKNOWN ⇒ cost is None`; `KNOWN ⇒ pricing_source_ref present` (zero
     legal only under KNOWN with a trusted source); no code path stores or
     renders a source-less zero; v1 payloads without `cost_status` decode as
     UNKNOWN+None (historical zeros projected, raw events never rewritten);
   - TUI approval is digest-bound; resume after restart reproduces the exact
     session.
3. Wave 1 + M1 suites green with E1–E3 extension tests; no substrate file
   outside the E1–E3 whitelist modified.
4. Headless TUI tests (textual pilot on scripted frames); scripted-chunk
   `DeterministicProvider` streaming tests without network; one recorded
   live-provider TUI session (streaming, in-TUI approval, mode use, restart
   resume, tokens + `UNKNOWN` cost).
5. D2 boundary test: no governance/runtime module imports `textual`.
6. ruff clean; pyright 0 on changed files; wheels build; pre-existing failure
   debt unchanged or reduced, reported separately; independent exact-diff review
   passes with no unresolved required changes.

M2 exit condition: an operator completes one real multi-turn coding task in the
TUI against a real provider — streaming with gap/interrupt honesty, an in-TUI
approval, a permission-mode use with visible provenance, a mid-session restart
resume, accurate tokens and `UNKNOWN` cost.

## Explicit non-goals

- Durable per-chunk events; cost pricing/billing recovery (E3 renders `UNKNOWN`).
- Substrate changes beyond the enumerated E1–E3 surfaces.
- Sub-agents, MCP, background tasks, checkpoint/rollback, context compression,
  AGENTS.md auto-load, codebase indexing, git capabilities.
- Web/desktop/IDE surfaces; multi-workspace daemon hosting.
- Any autonomy / market-parity-as-capability / `R`-ledger claim.
- `WorkflowGraph` semantic changes; a second event store; domain semantics in
  Agent Core; provider keys in TUI payloads/logs/DB.
- Push, merge, release, external publication or customer commitment (push of the
  106 base commits plus the spec/state commits remains a separate founder
  gate).

## Stop conditions

Stop and return `REVISE_TO_SPEC` if implementation requires any of:

- reusing the durable Task event sequence/cursor as the transient stream cursor;
- client-minted turn ids, or any execute path other than the begin-turn
  round-trip, or a duplicate begin-turn (same key + same digest) re-invoking
  the provider;
- replaying or re-binding a turn when an idempotency key returns with a
  different command digest (must fail typed `IDEMPOTENCY_CONFLICT`), or
  starting the provider on such a conflict;
- queueing, multiplexing, or starting a second in-flight turn on a session
  (must fail typed `TURN_IN_PROGRESS` with no provider start);
- a begin-turn without stream binding, or binding a turn to a stream the server
  did not validate as live;
- accepting a stale-generation cursor as valid instead of failing typed
  `STREAM_GONE`, or treating cursors of different `stream_id`s as
  interchangeable, or enqueuing `gap` frames into the evictable buffer;
- any frame loss without an explicit `gap` frame, or fabricated/back-filled
  frames after interruption or crash;
- finalizing a turn from `stream_end` without the durable commit, inferring
  completion from the stall timeout, or persisting
  `STALLED_PENDING_DURABLE_STATE` as a durable Task event;
- recording an auto-allowed action as `ApprovalDecision` (any actor), or any mode
  auto-approving tier-3+/out-of-allowlist, or a model-settable mode;
- recording READ_ONLY auto-pass with `basis=permission_mode` or a
  `mode_event_id`;
- executing an out-of-allowlist action under any `ApprovalDecision`, or failing
  to record the durable DENY verdict with reason;
- storing or rendering a source-less zero for a real call, or `UNKNOWN` with a
  non-None cost, or `KNOWN` without `pricing_source_ref`, or rewriting raw
  historical usage events;
- substrate edits outside the E1–E3 whitelist;
- the TUI holding governance state or opening the database;
- any non-`textual` runtime dependency in the governance/runtime stack;
- implementing outside the sequenced worktree or on an unadopted head;
- weakening approval, risk-tiering, sandboxing, compensation or receipt binding
  to make the demo pass;
- constant-return or mock-success tests standing in for any path above.

## Review and execution gate

This card authorizes nothing until founder CTO gate 9 accepts this packet plus
the Context Pack and Architecture Brief update. Then the base sequencing
(section header) executes: `docs(product)` spec commit → `docs(state)`
correction commit → final base SHA → clean worktree → test-first implementation
→ independent exact-diff review. Push, merge, release remain separate founder
gates; CURRENT_STATE.yaml is updated at phase completion (repo first, then
root), claim levels reported separately.

## Revision history

- **2026-09-11 rev 1 → gate 1 `REVISE_TO_SPEC`.** Stale D1 facts; wrong Wave 1
  numbering.
- **2026-09-11 rev 2.** D1/D3 corrected against checkout; D2 approved.
- **2026-09-11 rev 3.** Wave 1 built on `b05d29b8`; over-claimed "zero substrate
  change" / streaming / receipt-cost.
- **2026-09-11 rev 4.** Substrate truth table; E1 transient-chunk decision; E2
  enumerated extension; E3 tokens+UNKNOWN. Gate 3: facts accepted.
- **2026-09-11 rev 5.** Gate 3's three P1 corrections frozen: E1 gains the
  full transient-stream protocol (independent endpoint/cursor, subscription-
  before-turn, frame binding, bounded buffer + explicit gap frames, completion
  ordering, crash-honest recovery); E2 recording semantics changed from
  "durable APPROVE" to "policy allowance with provenance"
  (`POLICY_VERDICT_RECORDED(basis=permission_mode, mode_event_id)`), fabricated
  `ApprovalDecision` banned; E3 schema frozen (`Decimal | None` +
  `cost_status` + `pricing_source_ref`, zero banned). Base sequencing frozen:
  no `docs(state)` landing until gate 4; final M2 base = state-correction
  commit SHA.
- **2026-09-11 rev 6.** Gate 4's five defects closed: E1 gains the
  begin-turn round-trip (`SurfaceBeginTurnCommand` + idempotency key; the
  server is the only `turn_id` source; a duplicate begin-turn never re-invokes
  the provider), generation-bound cursors (`runtime_boot_id` + typed
  `STREAM_GONE`/410 fallback, no cross-generation splicing), and read-path-
  synthesized `gap` control frames that can never be evicted; E2 freezes
  out-of-allowlist as unapprovable fail-closed deny with a durable
  `POLICY_VERDICT_RECORDED(DENY)` record; E3 adds schema version bumps (usage
  `"2.0"`, surface protocol `"1.1"`), v1 legacy decode (historical zeros
  projected as UNKNOWN+None, raw events never rewritten) and narrows the zero
  ban to source-less zeros. Duplicate D1 sentence removed from AB §13.3.
- **2026-09-11 rev 7.** Gate 5's defects closed: begin-turn now carries
  the pre-subscribed `{runtime_boot_id, stream_id}` and the server atomically
  binds the turn to a validated stream (invalid → typed `STREAM_GONE`, provider
  never started), closing the association race; same-generation stream identity
  frozen (valid-cursor reconnect keeps `stream_id`; new ids only on explicit
  resubscribe/termination/`STREAM_GONE`; cursors not interchangeable across
  streams); READ_ONLY auto-pass frozen as tier-default policy with NO
  mode-provenance record (three-record chain only for `ACCEPT_IN_WORKSPACE`
  tier-2 policy auto-allow); "finalizing…" gains a bounded stall threshold
  (never inferred completion); AB §13.5 rejected-designs count corrected
  (missing entries restored) and extended with the gate-5 rejections;
  base sequencing re-frozen so the accepted spec lands as a `docs(product)`
  commit **before** the `docs(state)` correction, making the accepted packet
  an ancestor of the final M2 base.
- **2026-09-11 rev 8 (this).** Gate 6's two narrow P1 closed: idempotency-key
  conflict semantics frozen — the idempotency record binds a canonical command
  digest (session, statement, `{runtime_boot_id, stream_id}`, caller identity);
  same key + same digest replays, same key + different digest fails typed
  `IDEMPOTENCY_CONFLICT` with no provider start and no re-bind. Stall state
  fixed as the single typed value `STALLED_PENDING_DURABLE_STATE` — a
  transient client state, never a durable Task event, overruled only by the
  durable projection; the stall threshold is configurable, test-injectable,
  finite positive, with a fixed default. AB §13.5 extended to 22 entries.
  E1–E3 design not reopened. Status: `RESUBMISSION_PENDING_CTO_GATE_7`.
- **2026-09-11 rev 9 (this).** Gate 7's one P1 + two P2 closed: E1 gains the
  frozen in-flight concurrency model — one in-flight turn per session, a
  second begin-turn fails typed `TURN_IN_PROGRESS` (no provider start, no
  queueing, no multiplexing); E2 gains the positive bypass assertion —
  under `ACCEPT_IN_WORKSPACE` a tier-2 in-sandbox action is policy
  auto-allowed with the three-record chain present and `mode_event_id`
  resolvable, so a constant-deny implementation fails the suite; the stall
  threshold default is pinned to **30 seconds** (named constant, still
  configurable and test-injectable). E1–E3 design not reopened. Status:
  `RESUBMISSION_PENDING_CTO_GATE_8`.
- **2026-09-11 rev 10 (this).** Gate 8's one P2 (G8-1) closed: eight stale
  gate-7/rev-8 label residues corrected across GC/CP/AB — forward sequencing
  references now name gate 9 (the gate accepting this packet); backward status
  headers read "after gate 8"; contract provenance tags restated as "frozen at
  rev 8; unchanged through rev 10". Label-only edit: no contract, matrix,
  threshold, or sequencing change; E1–E3 design not reopened. Status:
  `RESUBMISSION_PENDING_CTO_GATE_9`.
