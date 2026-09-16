# Goal Card + CP/AB — S4 DETERMINISTIC CONTEXT COMPACTION

> Status: `IMPLEMENTED / PENDING_INDEPENDENT_EXACT_DIFF_REVIEW`
> Track: Product Track, medium risk (Agent Core runtime / ProviderRequest path).
> Cast: P2-7 M1 route A, target Python core. Base `origin/main` @ `18d7b9b0`.
> Claim ceiling: no parity / autonomy / release claim.

## 1. Goal

GAP-ANALYSIS M1 item: *"上下文压缩（手动+自动）— 无（GC P1+：deterministic compaction
recorded as event——注意本地要求压缩本身入事件流，比对标更严）"*. Before this slice the
loop trimmed history implicitly (silently dropping old USER-boundary groups) with no
durable record of the compaction.

## 2. What was implemented

- `contracts/runtime.py`: additive `TaskEventType.SESSION_CONTEXT_COMPACTED`.
- `agent_loop.py`:
  - `_compact_history()` returns the messages to send plus, **only when it actually
    dropped messages**, a deterministic payload: `chars_before`, `chars_after`,
    `dropped_messages`, `kept_from_index`, `retained_digest` (sha256 over roles, tool
    call ids/calls and content of the retained history). A no-drop evaluation returns
    `None` and records nothing (evidence honesty).
  - **The active request always survives**: cuts happen only at USER boundaries and
    never from the most recent USER message onward (`limit = last_user`), so an
    ASSISTANT `tool_calls` message and its TOOL replies are never split, and the
    in-flight user turn is never dropped.
  - `_maybe_record_compaction()` records the event durably once per distinct result
    per loop instance.
- `task_aggregate.py`: the new chat-turn audit marker carries no aggregate state
  transition (same as the other SESSION_* markers).

## 3. Boundaries

- No authority/permission/C7 change; no capability or tool semantics change. The
  ProviderRequest still binds the same task/run/profile/capabilities; only the
  `messages` list may be a compacted suffix.
- Compaction is deterministic: same history + budget ⇒ same `retained_digest`.

## 4. Verification

- `tests/product/test_context_compaction.py` (9): drops the oldest turn and keeps the
  active request; never splits a tool group; no compaction within budget; a single
  over-budget turn records no event; digest determinism; `_maybe_record_compaction`
  writes exactly one event per distinct result; two distinct compactions are both
  recorded; the projection replays a compaction event safely; no event for a large
  budget.
- Full `tests/product` 24 failed == base + 1 order-sensitive flaky mode-matrix test
  that passes in isolation (zero real new). Ruff clean; pyright 0.

## 5. Residual / honesty

- **`max_context_chars` is a soft target, not a hard cap**: the active turn (from the
  most recent USER message onward) is never dropped, so a single over-budget turn is
  kept in full and no event is recorded. Compaction only removes whole *completed*
  turns older than the active one.
- One event is recorded per distinct `(dropped_messages, kept_from_index)` per loop
  instance; events are bounded by turns, not steps.
- Compaction drops whole pre-active turns only; it does not summarise/rewrite content
  (that would need a model and a different gate). "Manual" compaction is out of scope.
- Independent exact-diff review still required before promotion.
