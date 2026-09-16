# Independent Exact-Diff Review — S4 Deterministic Context Compaction

> Commit under review: `62e47309` (parent `84ab583a`, base `origin/main` `18d7b9b0`)
> Worktree: `autonomous-agent-core/.worktrees/m1-danger-cmd-20260915`
> Gate doc: `.agent_runs/m1-context-compaction-s4-20260915/goal-card-cp-ab.md`
> Scope: Product Track, medium risk (Agent Core runtime / ProviderRequest path)
> Reviewer disposition: independent adversarial exact-diff; source/tests read-only.

## 0. What was reviewed

`git show --stat 62e47309` / `git diff 84ab583a..62e47309`:

- `packages/contracts/src/agent_os_contracts/runtime.py`: +1 additive enum value
  `TaskEventType.SESSION_CONTEXT_COMPACTED`.
- `packages/os_core/src/agent_os_core/agent_loop.py`: `_trimmed_history()` renamed and
  reworked into `_compact_history()` (+ payload), new `_maybe_record_compaction()`,
  new module-level `_history_digest()`, `_last_compaction` field, call-site swap at
  `messages=tuple(messages)`.
- `packages/os_core/src/agent_os_core/task_aggregate.py`: new event added to the
  "chat-turn audit marker" no-op set.
- `tests/product/test_context_compaction.py`: new (6 tests).

The authority-relevant surface of `_call_provider` (`agent_loop.py:1190-1199`) is
unchanged apart from the `messages` value; `task_id`, `run_id`, `provider_profile_id`,
`allowed_capability_ids`, `timeout_seconds`, and the pre/post invocation-binding and
correction checks are byte-for-byte the same. That part is clean.

## 1. Verification of the six required properties

### (a) Active (last) USER never dropped; tool group never split — PASS

`_compact_history` computes `last_user = max index with role USER` and
`limit = last_user`; the cut loop is bounded by `cut < limit` and the inner group loop
is bounded by `cut < limit` (`agent_loop.py:1595-1607`). `cut` therefore never exceeds
the last USER index, so `kept = [history[0], *history[cut:]]` always retains the active
turn, and because every drop starts at a USER index the retained suffix never begins
with an orphan TOOL. Verified:

- `[SYS, USER1, ASST, TOOL, USER2]` budget 40 → roles `[SYSTEM, USER]`, dropped 3
  (whole prior group), active `USER2` retained.
- All-USER `[SYS, U1, U2, U3]` → retains `[SYS, U3]`.
- Trailing ASSISTANT/TOOL after the last USER are always retained.

No infinite loop: every iteration of the outer `while` strictly increments `cut`, which
is bounded by `limit` (`agent_loop.py:1597-1607`).

### (b) Determinism — PASS (untested by the new suite)

`_history_digest` iterates the retained messages in fixed order and hashes
role+content with separators (`agent_loop.py:1619-1628`). Same history + budget ⇒ same
`retained_digest`; confirmed experimentally (`dig(h) == dig(h)`).
Caveat F5 below: the digest omits `tool_call_id`/`tool_calls`, and no test asserts
cross-instance/cross-run digest equality — the tests only assert `len(...) == 64`.

### (c) ProviderRequest authority unchanged — PASS

Only `messages` changes (`agent_loop.py:1195`). The binding checks
(`agent_loop.py:1159-1187`) and `allowed_capability_ids=CHAT_CAPABILITY_IDS`,
`provider_profile_id`, `timeout_seconds`, `task_id`, `run_id` are unchanged. Compaction
cannot widen authority, and it never mutates `self._history` (only the sent list).

### (d) Bounded event cardinality (not once per step) — FAIL

`_maybe_record_compaction` dedups on `(dropped_messages, chars_after)`
(`agent_loop.py:1561`). `chars_after` grows on every appended assistant/tool message,
so a distinct key is produced on each step once the budget is exceeded — i.e. one
event per step, not one per turn. Direct reproduction (same loop instance, 6 appends
onto `[SYS, USER1]`, budget 50):

```
A: events = 4
  {chars_before: 60, chars_after: 60, dropped_messages: 0, kept_from_index: 1}
  {chars_before: 84, chars_after: 84, dropped_messages: 0, kept_from_index: 1}
  {chars_before:108, chars_after:108, dropped_messages: 0, kept_from_index: 1}
  {chars_before:132, chars_after:132, dropped_messages: 0, kept_from_index: 1}
```

The goal-card residual ("events are bounded by turns, not steps", goal-card §5) is
therefore factually wrong. The unit test `test_maybe_record_compaction_writes_exactly_one_event`
only tests two *identical* payloads, so it cannot detect this; there is no test that
exercises multiple growing compaction results.

### (e) Aggregate handles the new event as a no-op — PASS (with a projection caveat)

`task_aggregate.py:456` adds it to the no-op marker set; it is not in
`PROTECTED_TRUTH_EVENTS` (`task_service.py:78-88`), so `append_event` accepts it. A real
turn completes and the event is readable. Caveat F4: `session_projection` does not
handle the event at all; it survives only because the payload has no `session_id`
(see F4).

### (f) Edge cases — PARTIAL

- Empty history + non-positive budget → `IndexError` at `kept = [history[0], ...]`
  (`agent_loop.py:1608`). Reproduced. Unreachable through the product path today:
  `AgentLoop.__init__` (`agent_loop.py:258`) requires exactly one leading system
  message and `SessionLoopConfig.__post_init__` (`session_projection.py:46-54`)
  requires `max_context_chars > 0`. Latent robustness bug only (F6).
- Only-system history + tiny budget → no crash, but emits a false compaction payload
  (`dropped_messages=0`). Reproduced.
- Budget 0 / negative via the product path → rejected by `SessionLoopConfig`
  ("session loop configuration limits must be positive"), so those values cannot reach
  `_compact_history` through `open_chat_session`. They are reachable only by assigning
  `loop._config` directly, which only tests do.
- message role TOOL at the cut boundary → not reachable by construction: the cut always
  lands on a USER index (or stops at `limit`, which is a USER index).

## 2. Findings

| ID | Severity | Finding |
|----|----------|---------|
| F1 | Medium (High for evidence honesty) | No-op "compaction" is recorded. `_compact_history` returns a non-`None` payload whenever `chars_before > budget`, even when `cut == 1` and nothing was dropped (`dropped_messages = 0`, `chars_before == chars_after`, `kept_from_index = 1`). This is the *normal* case within a single active turn because `limit = last_user = 1`. A durable `SESSION_CONTEXT_COMPACTED` event is emitted that asserts a compaction that never happened. `agent_loop.py:1586-1616`. |
| F2 | Medium | Event cardinality is per-step, not per-turn (see (d)). Dedup key uses `chars_after`, which grows every step. `agent_loop.py:1561`. Violates the stated verification criterion (d). |
| F3 | Low-Medium | `max_context_chars` is not actually enforced. Because the cut is bounded by `last_user`, the retained suffix (active turn + all of its tool output) can exceed the budget without limit; compaction only ever removes whole prior turns. The docstring/commit message "deterministically compact history to `max_context_chars`" overstates the behavior. `agent_loop.py:1575-1607`. |
| F4 | Medium | `session_projection._strict_project` has no branch for `SESSION_CONTEXT_COMPACTED`; it raises `SessionProjectionError("unsupported session event")` for any unhandled session event (`session_projection.py:547`). The event is excluded only implicitly, because its payload omits `session_id` and the projection pre-filter is `payload.get("session_id") == session_id` (`session_projection.py:227`). This is fragile: if the payload ever gains `session_id` (desirable for scope/attribution, and every sibling `SESSION_*` marker carries it), resume/projection will hard-fail. There is no test that resumes/projects a compacted session. |
| F5 | Low | `_history_digest` hashes only role+content, ignoring `tool_call_id` and `tool_calls`; two structurally different retained histories can share a `retained_digest`. The digest also does not bind the budget or cut. Adequate for the narrow stated claim, weak as an audit digest. `agent_loop.py:1619-1628`. |
| F6 | Low | Empty history + non-positive budget raises `IndexError`. Unreachable via the product path today; still a cheap defensive guard. |
| F7 | Low (test quality) | `test_compaction_is_recorded_over_the_turn_path` asserts only `chars_before >= chars_after` and event presence, which is satisfied by the no-op F1 case; it does not assert that any message was actually dropped, so it blesses the defect. `test_compaction_never_splits_a_tool_group` asserts only `kept[-1].content == "u2"`, which a bypass returning `[system, last_user]` would also satisfy; it does not check block closure. |

## 3. Explicitly checked and NOT found

- No infinite loop / unbounded loop (cut strictly increases, bounded by `limit`).
- Active request dropped: not possible under the current logic.
- Tool group split: not possible under the current logic.
- Authority widening: none; ProviderRequest fields other than `messages` are unchanged.
- Determinism: holds.
- Aggregate dispatch: handled as a no-op; event is not protected and thus appendable.
- Existing `test_trimmed_history_keeps_tool_blocks_atomic` still passes (1 passed).

## 4. Test run

```
uv run --extra product-test pytest tests/product/test_context_compaction.py -q
......                                                                   [100%]
6 passed in 2.67s
```

Also ran `pytest tests/product/test_terminal_chat_loop.py -k "trimmed or context or
compaction or history" -q` → `1 passed, 34 deselected`.

Count of the requested target suite: **6 passed**.

## 5. Required changes before promotion

1. **Do not emit a compaction when nothing was dropped.** Return `None` (or suppress the
   record) when `cut == 1` / `dropped_messages == 0`; a `SESSION_CONTEXT_COMPACTED`
   event must imply at least one dropped message. Fixes F1 and part of F2.
2. **Make the dedup bound per-turn/per-boundary, not per-step.** Key the dedup on the
   cut boundary (`dropped_messages` and/or `kept_from_index`), not on `chars_after`, so
   a single turn cannot produce one event per step. Fixes F2 and makes goal-card §5
   truthful.
3. **Add explicit projection handling.** Add a no-op branch for
   `SESSION_CONTEXT_COMPACTED` in `session_projection._strict_project`, and add
   `session_id` to the payload for scope consistency; add a resume/project test that
   replays a compacted session. Fixes F4.
4. **Correct the doc/claim language** — either implement real budget enforcement or
   state precisely that compaction only drops whole pre-active turns and the active
   turn may exceed `max_context_chars`. Fixes F3.
5. **Strengthen tests to be bypass-detecting:** assert that a recorded event has
   `dropped_messages >= 1` and `chars_before > chars_after`; assert retained tool-block
   closure (reuse `_assert_tool_blocks_closed`); add a multi-step test asserting the
   per-turn event count; add a determinism-equality test. Fixes F7; also add a cheap
   empty-history guard (F6) and, preferably, bind `tool_call_id` in the digest (F5).

## 6. Independence limitation

The reviewing model is the same model family as the builder (`deepseek-flash`), so this
is a same-model review and does **not** satisfy the constitution's independent-reviewer
identity requirement. A different-provider reviewer remains required before promotion.

---

**VERDICT: APPROVE_WITH_CHANGES**
