# ADR-0063: Checkpoint / rewind — append-only epoch/branch model (no destructive rollback)

- Status: Accepted (founder ruling 2026-09-19; implemented on branch
  `feat/l4-audit-closure-20260919`)
- Date: 2026-09-19
- Deciders: founder (ruling 5); agent drafted and implemented the P0.
- Preserves: the append-only evidence spine, C7 epoch, UNKNOWN fail-closed
  gate, `docs/product/GC-CHECKPOINT-REWIND-2026-09-18.md`.
- Numbering check: `docs/adr/` max on baseline is `ADR-0062`. This ADR takes
  `ADR-0063` (signature = `ADR-0064`, versioning/distribution = `ADR-0065`).

## 1. Context

The runtime is event-sourced: every durable fact is an immutable append to the
session/task event stream (`SQLiteTaskEventStore`). Shard A already landed a
forward-only form: `SESSION_CHECKPOINT_RECORDED` markers plus read-only forward
replay (`surface_list_checkpoints` / `surface_replay_checkpoint`). The operator
needed to actually go *back*. The GC (`GC-CHECKPOINT-REWIND-2026-09-18.md`)
proved that true destructive rewind (deleting/truncating history) is forbidden:
it breaks the immutable evidence spine, breaks causality, and would let a
rewind silently erase approvals/outcomes.

## 2. Options considered

- **A — Destructive rewind (truncate history, restart).** Rejected. Violates the
  append-only spine; erases provenance of approvals, outcomes, and child
  burial; irreversibly loses evidence. The GC rejected this explicitly.
- **B — Mutate the current session's cursor and keep appending.** Rejected.
  Reusing the same session id after a "go back" reuses its run/permits/approvals
  (C7), which is a cross-epoch leakage, and leaves the contradictory old events
  in the same stream.
- **C — Snapshot the full conversation/memory and restore it.** Rejected for P0.
  Compaction (`SESSION_CONTEXT_COMPACTED`) already destroys original messages;
  keeping a second mutable snapshot duplicates state the spine does not own and
  reintroduces divergence between "what is proven" and "what the model sees".

## 3. Decision (chosen: C — append-only branch / new epoch)

"Rewind" is implemented as **forking a new epoch from a checkpoint**, not as
time travel:

1. The operator writes a named checkpoint (`SESSION_CHECKPOINT_RECORDED`,
   already shipped).
2. `surface_fork_from_checkpoint(command, checkpoint_label=...)` opens a brand
   NEW session (new task id, new run) whose durable stream begins with a
   `SESSION_FORKED_FROM_CHECKPOINT` lineage event binding
   `{parent_session_id, parent_task_id, checkpoint_sequence, checkpoint_label,
   parent_state_digest}`.
3. The PARENT session is CLOSED read-only (`SESSION_CLOSED`). Its events are
   never deleted, rewritten, or resequenced — the parent history stays sealed
   and readable.
4. The new epoch runs forward independently; it does NOT inherit the parent's
   permits/approvals and does NOT inject the parent's prior messages into model
   context (that is a P1 snapshot, out of P0 scope).

The fork event is in `PROTECTED_TRUTH_EVENTS`, written only by the typed writer
(`record_session_fork_from_checkpoint`), and carries no prompt/completion text.

## 4. Consequences and reversibility

- **Append-only integrity preserved.** Hermetic tests assert the parent event
  list is byte-identical (event_id, sequence, event_type, payload_json) before
  and after the fork; the only addition is the `SESSION_CLOSED` seal.
- **Reversible / forward-only.** Undoing a fork = stop using the new session;
  the parent remains sealed history. Nothing is destroyed.
- **Corrected epochs.** Consistent with ruling 5: an epoch that has been
  corrected (correction guard) cannot be resumed; the operator forks a new
  epoch after the correction point. This closes the "corrected session stays
  half-open" tail.
- **Not claimed.** This P0 does NOT (yet) re-seed model context from the
  checkpoint, does NOT resume parent permits, and does NOT run side-effect
  compensation. Those are P1 and require the GC's D1–D8 gates.

## 5. Test evidence

`tests/product/test_session_checkpoint.py`:
- pre-shard list/write/replay (2 tests, unchanged);
- `test_fork_from_checkpoint_branches_a_new_epoch_and_keeps_parent_immutable`
  (parent bytes identical, fork lineage event present, new epoch active);
- `test_fork_unknown_checkpoint_label_is_typed_rejection` (KeyError, no
  partial fork on missing label).
