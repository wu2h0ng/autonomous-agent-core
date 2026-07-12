# Agent OS bounded long-horizon implementation log

- Date: 2026-07-12
- Run: `agent-os-e2e-long-horizon-20260712`
- Track: Product only
- Branch: `codex/agent-os-e2e-long-horizon-20260712`
- Status: `BOUNDED_LONG_HORIZON_LOCAL_SLICE_VERIFIED`
- Evidence scope: `PRODUCT_LOCAL_ACCEPTANCE_ONLY`

## Objective and boundary

Extend the PM-accepted SPINE-0 local developer path with one bounded durable vertical:
typed wait/signal/deadline handling, dependency blocking, one explicit suffix rebind,
restart reconstruction, governed patch compensation, persistent C7 checks and an
event-derived recovery projection.

This task did not modify `src/aac`, `experiments`, research results, research gates or SPINE-1
migration state. It did not run `LH-RECOVERY-1` and does not claim multi-hour/day advantage,
multi-week execution, 7x24 autonomy, physical exactly-once, continual learning, self-evolution
or AGI.

## Implementation ownership

Founder changed the default ownership model during execution:

- Codex: architecture, engineering governance, primary review, integration and final
  verification. Codex had already implemented Tasks 1-6 before the ownership amendment.
- Claude Code: primary writer for the important three-scenario `LH_PRODUCT_SLICE_E2`
  acceptance suite.
  Authored commit `d6dab42`, integrated as `38d91a9`.
- OpenCode: primary writer for focused real HTTP/CLI persistence and negative-path tests.
  Authored commit `6aaa7b2`, integrated as `88a8918` after a Codex `REVISE` review replaced
  duplicated service-level tests with real public-surface tests.
- Kimi: primary writer for the real-execution partial-evidence rebind regression. Authored
  commit `733f0d9`, integrated as `879e286` after a Codex `REVISE` review added action binding,
  physical-artifact and exact ordering assertions.
- Cursor Agent: requested, but its CLI remained unauthenticated. No Cursor output is counted
  as evidence.
- Claude Code initially returned 401 until OAuth was refreshed. Its first Opus pass hit the
  bounded USD limit after writing a passing file; a second Claude Sonnet pass completed the
  reviewed assertions and commit.

The durable ownership decision, sessions, handoffs, blockers and completions are recorded in
`../.agent_runs/agent-os-e2e-long-horizon-20260712/`.

## Delivered contracts and event truth

- WAIT_EVENT nodes require a typed signal name and correlation key.
- `WorkflowGraph.max_replans` is frozen and bounded to 0..3.
- `ExternalSignal`, `WaitCondition`, `RunPlanRebound`, `RunRecoverySnapshot` and typed patch
  compensation records are immutable contracts.
- Commitment and wait deadlines are immutable. There is no deadline-extension surface.
- Signal satisfaction, wait completion and rebind state are append-only Task events.
- Exact signal replay is idempotent; mismatched reuse and scope spoofing fail without appending
  success events.
- Rebind replaces only an uncompleted suffix. Completed-prefix nodes and their evidence remain;
  partial/uncompleted evidence and stale proposals/approvals are removed.

## Delivered runtime behavior

- Coordinator stops at a durable wait, treats a live wait as an event-stream no-op, times out
  fail-closed, and resumes from the persisted signal in a reconstructed process.
- Lease rereads and optimistic state writes close status/rebind/approval races. Ordinary
  exceptions release a lease; `WorkerInterrupted` intentionally preserves it for explicit
  stale-worker recovery.
- Production artifact events bind `node_id` and `action_id`.
- `workspace.apply_patch` persists an immutable before-image manifest before replacing the
  target, uses fsync plus atomic rename, and validates path, intent, digest and state on replay.
- Compensation is an internal typed capability and still crosses PolicyKernel, permit, broker,
  correction and receipt gates. A user edit after the patch is never overwritten.
- Persistent correction epochs are live-read and atomically advanced. Final connector dispatch
  rechecks permit expiry, halt state and exact epochs before idempotency lookup or side effects.
- Automatic compensation preserves the original `FAILED/NOT_MET` result if compensation
  infrastructure fails. Missing durable bindings stop reverse compensation fail-closed.

## Public entries

Application, HTTP and CLI now share the same service/coordinator path for:

- external signal;
- bounded replan;
- external correction resume;
- explicit governed compensation;
- event-derived recovery projection.

HTTP is currently loopback/local and the composition root uses a fixed local Principal. This is
not production authentication or multi-tenant authorization evidence.

## Acceptance evidence

The Claude-authored `LH_PRODUCT_SLICE_E2` suite proves three local composition-root scenarios:

1. wait -> reconstructed process -> signal -> one rebind -> provider -> approval -> patch ->
   real pytest -> evaluator -> `VERIFIED`;
2. bad patch -> worker interruption -> reconstructed process -> `NOT_MET` -> exactly one
   automatic compensation restoring the original file;
3. C7 halt blocks automatic/manual rollback; ordinary task resume does not clear correction;
   Worker cannot resume it; Principal resume is audited before exactly one governed rollback.

Additional OpenCode and Kimi suites cover real HTTP/CLI denial paths and real partial-artifact
filtering after rebind.

## Commit sequence

- `c6ea525` bounded long-horizon contracts
- `e79180f` wait signals and bounded replans
- `e608393` durable wait and rebind execution
- `3cdf9c3` rebind authority races
- `b33510b` artifact binding and lease release
- `c482d12` persistent correction boundary
- `48760e3` restart-safe patch snapshots
- `91c0c6e` governed restart-safe compensation
- `87188e6` event-derived recovery projection
- `b825f44` governed public long-horizon controls
- `64db0d8` frozen convergence design and implementation plan
- `879e286` Kimi partial-evidence rebind regression
- `88a8918` OpenCode public HTTP/CLI negative paths
- `38d91a9` Claude three-scenario `LH_PRODUCT_SLICE_E2` acceptance vertical

## Independent review

- Coordinator/rebind review: `ACCEPT`, no P0/P1.
- Compensation/C7 review: `ACCEPT`, no P0/P1.
- Codex primary review: both supporting-agent first passes received evidence-backed `REVISE`
  findings, were repaired by their original authors, then accepted and integrated.

## Residual risks

- The pytest subprocess is not an OS-level hostile-code sandbox.
- Correction authority mutation and TaskEvent audit append are not one database transaction;
  an extreme crash can leave the audit projection behind authority truth.
- Reader/writer authority isolation is structural Python/process discipline, not a separate
  operating-system capability boundary.
- Test HTTP servers close via shutdown; the supporting suite does not additionally call
  `server_close()`.
- There is no scheduler, fleet manager, production identity provider, remote webhook
  authentication or long-duration workload evaluation in this slice.
