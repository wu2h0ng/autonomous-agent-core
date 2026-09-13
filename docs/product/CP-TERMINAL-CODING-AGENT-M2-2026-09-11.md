# Terminal Coding Agent Context Pack — M2 (rev 10: gate-8 label closure)

> Date: 2026-09-11 (revision 10, after CTO gate 8 `REVISE_TO_SPEC`)
> Track: Product
> Status: **SPECIFIED_ONLY / RESUBMISSION_PENDING_CTO_GATE_9**
> Post-acceptance (2026-09-14): **ACCEPTED_GATE_9** — landed `df4f6ef1`; terminal line merged via PR #13 `ecc82b13`; see `docs/product/GATE9-ACCEPTANCE-TERMINAL-CODING-AGENT-M2-2026-09-14.md`. The pending marker above is retained as gate history.
> Goal Card: `docs/product/GC-TERMINAL-CODING-AGENT-M2-2026-09-11.md` (rev 10)
> Architecture Brief: `docs/architecture/T-P-CORE-TERMINAL-CODING-AGENT-ARCHITECTURE.md` (§13, rev 10)
> Base sequencing (re-frozen at gate 5): gate 9 accepts rev 10 → in a temporary
> clean worktree of `b05d29b8`, land the accepted rev-10 packet as an independent
> `docs(product)` spec commit → land the CURRENT_STATE correction as a
> `docs(state)` commit on top → **the second commit's SHA is the final M2 exact
> base** (code baseline `b05d29b8` + accepted spec + state correction) → create
> the clean D1-step-2 worktree from that SHA and cut branch
> `codex/terminal-coding-agent-m2`. Nothing is landed before gate 9.
> D1 reconcile: `D1-RECONCILE-b05d29b8-2026-09-11.md` (workspace root)
> Substrate evidence: Wave 1 plan + `.agent_runs/native-surface-wave1-20260811/verification.md`
> UI design baseline: `docs/product/AGENT-SURFACE-UI-BENCHMARK-2026-08-15.md`
> Dated benchmark: `docs/product/TERMINAL-AGENT-CLI-BENCHMARK-2026-07-26.md`
> Line references are on `b05d29b8` (re-verified 2026-09-11).

## Reading order and authorities

1. Root workspace `AGENTS.md`: §5 track selection, §7 hard boundaries, §9
   taxonomy, §13 product flow, §14 engineering reality review, §16 Git
   finalization.
2. Repo `AGENTS.md`: §3 boundaries, §4 Product flow, §6 verification entry
   points, §8 Git hygiene, §12 one-writer discipline.
3. `docs/CURRENT_STATE.yaml` on `main` — except its stale Wave 1 status/boundary
   lines (correction text below, landing sequenced after gate 9). The
   feature-checkout copy is 575 commits stale; never use it for M2 truth.
4. `D1-RECONCILE-b05d29b8-2026-09-11.md`.
5. Goal Card rev 10 (governing spec), M0/M1 packet, Wave 1 plan + verification,
   UI benchmark, dated CLI benchmark (design target only).

## Substrate truth on the code baseline `b05d29b8` (three tiers, unchanged from rev 4)

- **Tier 1 — verified, adopt as-is:** session projection (`SessionProjector`,
  session_projection.py:195), durable transcripts + restart resume, durable
  deferred-approval continuation, `SurfaceRuntime` (surface_runtime.py:118),
  authenticated HTTP + resumable SSE over committed events, daemon lifecycle,
  blocking `SurfaceClient` commands.
- **Tier 2 — primitives only:** `ProviderPort.complete_streaming`
  (provider.py:122/167/332) + SSE parser with malformed-delta fail-closed; but
  `AgentLoop` still calls non-streaming `complete()` (agent_loop.py:1148), no
  chunk propagation exists, and `SurfaceClient` (surface_client.py:62, run_turn
  line 177) is blocking JSON with no incremental consumer.
- **Tier 3 — missing, M2 builds (only authorized substrate edits):**

## E1/E2/E3 frozen contracts (frozen at rev 8; unchanged through rev 10; these are the packet's core)

**E1 transient-stream protocol (gate-3 frozen; gate-4/5/6 defects closed):**

- Separate session-stream endpoint `GET /v1/sessions/{session_id}/stream` with a
  **frame-level transient cursor** (`Last-Event-ID`). The durable Task event
  sequence/cursor is NOT reused — mixed cursors produce undecidable gaps.
- **Generation binding:** every frame is bound to
  `(runtime_boot_id, stream_id, turn_id, frame_sequence)`; every cursor is
  `(runtime_boot_id, stream_id, frame_sequence)`; `runtime_boot_id` changes on
  every daemon restart, so dead-generation sequences cannot collide. A reconnect
  presenting a stale generation fails typed `STREAM_GONE` (HTTP 410 + typed
  body) → durable snapshot fallback → resubscribe under the new generation.
  Never splice frames across generations.
- **Stream identity within one generation:** a reconnect presenting a
  valid transient cursor MUST keep the original `stream_id`; a new `stream_id`
  is minted only on explicit new subscription, on stream termination, or after
  `STREAM_GONE`. Cursors of different `stream_id`s are not interchangeable.
- **Turn-start (no launch race, no association race):**
  `SurfaceBeginTurnCommand` (reserve/begin-turn). Order: TUI subscribes first
  (gets `stream_id` under the current `runtime_boot_id`) → issues begin-turn
  carrying the statement, an **idempotency key**, and the pre-subscribed
  **`{runtime_boot_id, stream_id}`** → the server validates the stream is still
  live, **atomically binds** the turn to that stream, durably records
  turn-start, returns authoritative `{turn_id, stream_id}` → the turn executes
  asynchronously. An invalid stream reference fails typed `STREAM_GONE` and the
  provider is never started. Begin-turn is the single execution trigger.
  Clients never mint turn ids.
- **In-flight turn concurrency (rev 9):** one in-flight turn per session — a
  begin-turn arriving while a prior turn is uncommitted fails typed
  **`TURN_IN_PROGRESS`** (provider never started; no queueing, no
  multiplexing); the next turn is submitted only after the durable commit of
  the prior one.
- **Idempotency conflict semantics (rev 8):** the idempotency record binds a
  **canonical command digest** covering at least the session, the statement,
  `{runtime_boot_id, stream_id}` and the caller identity. Same key + same
  digest replays (returns recorded ids, never re-invokes the provider); same
  key + different digest fails typed **`IDEMPOTENCY_CONFLICT`** — provider
  never started, turn never re-bound.
- Frames carry `{runtime_boot_id, stream_id, turn_id, frame_sequence}`; the
  client renders only frames matching the current stream+turn and discards
  stale frames after an explicit terminal frame for that turn.
- Bounded per-stream buffer; overflow may disconnect the slow consumer, never
  silently drops. **Gap frames are synthesized on the read path**: whenever the
  consumer cursor is below the earliest retained sequence, the server emits an
  explicit `gap` control frame (`gap_from/gap_to`) ahead of retained frames — a
  priority control frame, never enqueued into the evictable buffer.
- Reconnect resumes from the transient cursor; missed ranges render as explicit
  gaps; if the durable turn committed, the client may re-render final from the
  durable snapshot.
- `stream_end` ≠ completion: the durable turn commit (typed `stop_reason`) is
  authoritative for final rendering; stream-end-without-commit renders
  "finalizing…" and resolves only from durable state. **Bounded stall (rev 8):**
  if no durable commit arrives within a bounded stall threshold, the TUI renders
  the single typed state **`STALLED_PENDING_DURABLE_STATE`** — a transient
  client state, never a durable Task event; it never infers completion from the
  timeout and is overruled only by the durable projection. The threshold is a
  finite positive value, configurable and test-injectable, with a fixed
  default of **30 seconds** (a named constant).
- Daemon crash: transient state dies (new `runtime_boot_id` on restart; stale
  cursors fail typed); recovery from durable projection only; in-flight turn
  shows terminated; no back-fill, no fabrication.

**E2 recording semantics (gate-3 frozen; gate-4/5 defects closed):**

- Auto-allowance is never an `ApprovalDecision`. Durable record for a
  permission-mode auto-allowed action =
  `SESSION_PERMISSION_MODE_SET` (once per change, names the operator) +
  `POLICY_VERDICT_RECORDED(ALLOW, basis=permission_mode, mode_event_id=…)` +
  normal `ActionPermit`/receipt.
- **READ_ONLY audit semantics:** READ_ONLY auto-pass is pre-existing
  tier-default policy — NO `basis=permission_mode` record, NO `mode_event_id`.
  The three-record mode-provenance chain applies only to tier-2 in-sandbox
  policy auto-allow under `ACCEPT_IN_WORKSPACE`.
- `ApprovalDecision` remains exclusively human (principal/admin, exact digest).
- **Decision rule:** tier-3+ **in-allowlist** requires a real human
  `ApprovalDecision` in every mode; out-of-allowlist / sandbox escape is
  **never executable** — fail-closed deny, unapprovable. An
  `ApprovalDecision(APPROVE)` for an out-of-allowlist action never executes;
  the attempt is recorded durably as `POLICY_VERDICT_RECORDED(DENY,
  basis=out_of_allowlist, reason=…)` with the action digest.
- Matrix (frozen): READ_ONLY auto-pass (tier-default, no mode record) in all
  modes; tier-2 in-sandbox edit interactive in ASK/ACCEPT_READ_ONLY, policy
  auto-allow in ACCEPT_IN_WORKSPACE; tier-3+ in-allowlist interactive in all
  modes; out-of-allowlist fail-closed deny (unapprovable) in all modes.

**E3 storage schema (gate-3 frozen, gate-4 defects closed; unchanged since rev 6):**

- `ProviderUsage.estimated_cost_usd: Decimal | None = None`; required
  `cost_status: Literal["KNOWN","UNKNOWN"]`; optional `pricing_source_ref`.
  Version bumps: usage contract `"2.0"`, surface protocol `"1.1"` (additive).
- Invariants: `UNKNOWN ⇒ None`; `KNOWN ⇒ pricing_source_ref present`. Zero is
  legal only under `KNOWN` with a trusted price source (genuinely free models);
  the ban is on **source-less zero**. Provider writes `UNKNOWN`/`None` until a
  versioned price source exists; never a source-less `0`. TUI masking alone
  insufficient — storage stops producing pseudo-precise zeros.
- **Legacy compatibility:** v1 payloads without `cost_status` decode as
  `UNKNOWN`/`None`; historical stored zeros are projected as UNKNOWN+None at
  read/projection time. Raw historical events are never rewritten (append-only
  store). All in-repo producers, fixtures and event/receipt readers migrate in
  the same M2 change; readers accept v1 payloads for replay indefinitely.
- Tokens: real usage propagated per turn/session (`SurfaceTurnResponse.
  total_tokens` exists).

**Governance spine (unchanged):** `PolicyKernel.decide()` / permits,
`WorkspaceSandbox` + snapshot compensation, correction epochs, one event store;
provider keys environment-resolved only.

**M1 lineage:** governed loop, approval non-bypass, live kimi-k2 verification
2026-08-06. Wave 2 Tauri (`apps/macos/`) is separate authorization; M2 does not
extend it.

## Market capability matrix (design target, not a parity claim)

| Market capability | Status at baseline | M2 disposition |
| --- | --- | --- |
| Session resume / durable transcript | built + verified (Tier 1) | adopt/verify e2e via TUI |
| Loopback protocol client (commands) | built + verified (blocking) | TUI mounts per D3 |
| Streaming transport (provider parse) | primitive only (Tier 2) | **E1** with frozen stream protocol |
| Incremental client streaming | missing | **E1** |
| Rich terminal TUI | missing | **P0** (`textual`, D2 approved) |
| Permission modes | missing incl. protocol | **E2** with provenance recording |
| Token visibility | partial (turn total_tokens) | **E3** accurate per-turn/session |
| Cost visibility | fake zero (provider.py:225/461/593) | **E3** `UNKNOWN`-only + v1 legacy decode, schema frozen |
| Compression / AGENTS.md / indexing / checkpoint | missing | P1+ / non-goal |
| Sub-agents / MCP / background tasks | missing | non-goal (M4 lineage) |

## Working-tree condition (unchanged)

- Main checkout stale (15/575) + dirty with other tasks' changes; not an M2 base.
- `.worktrees/agent-tui-product-fix` dirty — excluded; `.worktrees/ide-ui` hosts
  other work — excluded.
- Worktree is created only after base sequencing (gate 9 → `docs(product)` spec
  commit → `docs(state)` correction commit → final base SHA → new clean
  worktree).

## Constraints that bind implementation

- **Extension whitelist:** substrate edits limited to E1–E3 surfaces; all other
  substrate files byte-identical; exact-diff review checks the whitelist.
- **D2 (approved):** `textual`, UI-only, pinned; automatic import-boundary test.
- **D3 (approved direction):** protocol client; E1's incremental consumer and
  E2's mode command are the protocol deltas.
- Test-first (root §7.3; repo §4), minimum bypass set: begin-turn as the only
  `turn_id` source, carrying the pre-subscribed `{runtime_boot_id, stream_id}`
  with server-side stream validation (invalid → `STREAM_GONE`, provider never
  started); idempotency binds the canonical command digest (session +
  statement + stream binding + caller identity): same key + same digest
  replays without provider re-invocation, same key + different digest fails
  typed `IDEMPOTENCY_CONFLICT` (no provider start, no re-bind); a begin-turn
  while a prior turn is uncommitted fails typed `TURN_IN_PROGRESS` (no
  provider start, no queueing, no multiplexing);
  subscription-before-execution; frame binding; stale-generation cursor → typed
  `STREAM_GONE` with no cross-generation splicing; same-generation
  valid-cursor reconnect keeps `stream_id`; cursors not interchangeable across
  streams; read-path-synthesized gap frames (no silent loss, gap never
  evicted); no finalize-without-commit; stall timeout renders only the single
  typed `STALLED_PENDING_DURABLE_STATE` (transient, never durable, threshold
  configurable/test-injectable with a fixed 30-second default); crash recovery honest;
  no-mode-auto-approves-tier3+; out-of-allowlist unapprovable (APPROVE never
  executes; durable DENY verdict recorded); model-cannot-set-mode; under
  `ACCEPT_IN_WORKSPACE` tier-2 in-sandbox actions are policy auto-allowed with
  the three-record chain present and `mode_event_id` resolvable (positive path —
  a constant-deny implementation must fail); every
  permission-mode auto-allowed action has a verdict record with valid
  mode_event_id; READ_ONLY auto-pass produces no mode-provenance record;
  **zero ApprovalDecision rows for auto-allowed actions**; `UNKNOWN ⇒ None`;
  `KNOWN ⇒ pricing_source_ref` (zero legal only with a trusted source); no
  source-less-zero path; v1 legacy decode with raw events never rewritten;
  resume exactness; TUI approval digest-bound.
- Wave 1 + M1 suites green with E1–E3 extension tests; Wave 1 carried minor
  items closed only where blocking, as separate small commits.
- No pseudo implementation; C7 non-writable; provider keys never in payloads/
  SQLite/logs; one writer per scope; independent exact-diff review; no
  push/merge/release by this packet.

## Decision status (after gate 8)

- **D1:** code baseline `b05d29b8`; final M2 base = the `docs(state)` correction
  commit SHA, preceded by the `docs(product)` spec commit (sequenced
  post-gate-8). Adoption recorded at gate 2.
- **D2:** APPROVED. **D3:** APPROVED (protocol client).
- **E1/E2/E3:** gate 3 `REVISE_TO_SPEC` → frozen in rev 5; gate 4
  `REVISE_TO_SPEC` → five defects closed in rev 6; gate 5 `REVISE_TO_SPEC` →
  six defects closed in rev 7; gate 6 `REVISE_TO_SPEC` → two narrow defects
  closed in rev 8; gate 7 `REVISE_TO_SPEC` → three defects closed in rev 9;
  gate 8 `REVISE_TO_SPEC` (G8-1, label residues) → closed in rev 10;
  gate 9 verifies the closure.

## Companion state correction (text frozen; landing sequenced after gate 9)

Main `docs/CURRENT_STATE.yaml`, Wave 1 entry (`P-NATIVE-SURFACE-WAVE1-20260811`):

1. Status field:
   - from: `... / NOT_MERGED / BRANCH_CONTAINED codex/native-surface-wave1-20260811`
   - to: `... / MERGED_IN_LOCAL_MAIN (ancestors of b05d29b8, reconciled 2026-09-11) / BRANCH codex/native-surface-wave1-20260811 historical`
2. Boundary field, first sentence:
   - from: `Wave 1 is branch-contained on codex/native-surface-wave1-20260811 from plan base 7bfb1753 and is NOT pushed, merged, released, notarized, or daily-usable.`
   - to: `Wave 1 is merged into local main (ancestors of local main b05d29b8; per-task approved heads 2615b10e/1a82e6a5/447f4dd9/9bcd22fb/641cc847 + Task 9 final; reconciled 2026-09-11) and is NOT pushed, released, notarized, or daily-usable; the implementation branch is historical.`

Landing route: temporary clean worktree of `b05d29b8`; first the accepted rev-10
packet lands as an independent `docs(product)` spec commit, then this correction
as a single `docs(state)` commit; worktree removed. The second commit's SHA
becomes the final M2 base. Nothing else on `main` changes. Executed only after
gate 9 acceptance.

## Verification entry points (repo `AGENTS.md` §6)

```bash
uv run --extra product-test pytest tests/product -q
uv run --extra product-test ruff check apps packages/contracts/src packages/os_core/src tests/product
uv run --extra product-test pyright apps packages/contracts/src packages/os_core/src tests/product
uv build --wheel --out-dir /tmp/agent-os-product-wheel packages/contracts
uv build --wheel --out-dir /tmp/agent-os-product-wheel packages/os_core
```

M2 additionally requires: Wave 1 + M1 suites green with E1–E3 tests; headless TUI
tests (textual pilot on scripted frames); scripted-chunk streaming tests on
`DeterministicProvider`; begin-turn binding/idempotency tests (unbound or
invalid-stream begin-turn rejected with `STREAM_GONE` and no provider start;
duplicate begin-turn never double-invokes the provider; same key + different
digest fails typed `IDEMPOTENCY_CONFLICT`; a begin-turn during an uncommitted
prior turn fails typed `TURN_IN_PROGRESS` with no provider start);
stale-generation and
same-generation reconnect tests (`stream_id` stability, non-interchangeable
cursors); stall-threshold tests (typed `STALLED_PENDING_DURABLE_STATE` only,
threshold injected in tests); v1 legacy usage-decode tests; D2
import-boundary test; one recorded live-provider TUI session; independent
exact-diff review including the substrate whitelist check. Passing base gates
is necessary, not sufficient.

## Evidence and claim boundary

- Product-ledger evidence only; no research/process/commercial backfill.
- "Market parity" is a design target, never a competitive/customer statement.
- Tier 1 rows claim Wave 1's recorded heads; E1–E3 are explicitly new work —
  nothing in them may be described as pre-existing in any claim or demo.
- Claim levels reported separately; pre-implementation ceiling `specified`.
- Live-provider verification manual and recorded; CI uses `DeterministicProvider`.
