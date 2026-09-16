# Independent Exact-Diff RE-REVIEW (R3) — M1 S4 Deterministic Context Compaction

> Fix commit under review: `1f85bc9f` + docs `03d7ae76`
> Parent: `3098ddbf`; base `origin/main`: `18d7b9b0`
> Worktree: `autonomous-agent-core/.worktrees/m1-danger-cmd-20260915`
> Prior reports: `.agent_runs/m1-context-compaction-s4-20260915/review-subagent.md`, `review-subagent-r2.md`
> Disposition: independent adversarial exact-diff third review; source/tests read-only.
> Scope: Product Track, medium risk (Agent Core runtime / ProviderRequest path).

## 0. Diff reviewed

`git diff 3098ddbf..HEAD` touches only:

- `agent_loop.py`:
  - dedup key `(dropped_messages, kept_from_index)` → `(dropped_messages, kept_from_index, retained_digest)` (`agent_loop.py:1561-1565`).
  - new no-USER guard `if last_user == 0: return history, None` (`agent_loop.py:1600-1602`).
  - `_last_compaction` annotation `tuple[object, object] | None` → `tuple[object, ...] | None` (`agent_loop.py:275`).
- `tests/product/test_context_compaction.py`: adds `test_projection_ignores_a_recorded_compaction` (`:240-255`) and `test_two_distinct_compactions_are_both_recorded` (`:258-267`).
- `.agent_runs/.../goal-card-cp-ab.md`: §4 corrected to 9 tests.
- `.agent_runs/.../review-subagent-r2.md`: prior report committed.

No change to the authority surface (`_call_provider` binding/`ProviderRequest` fields byte-identical), permissions, C7, or capability semantics. `ruff` clean; `pyright` 0 errors.

## 1. Per-finding adjudication (R2 F7-F10)

| ID | Prior severity | Status | Evidence |
|----|----------------|--------|----------|
| F7 | LOW (tests) | **OPEN (partially closed)** | (iii) A projection test now exists: `test_projection_ignores_a_recorded_compaction` (`test_context_compaction.py:240-255`) writes a real `SESSION_CONTEXT_COMPACTED` event then `project_session` succeeds. It is genuine at the store-replay level **but does not exercise the new `session_projection` branch**: the payload has no `session_id` (probe confirmed), so `project_session` pre-filters it at `session_projection.py:227` before `_strict_project`, and the test passes identically if the branch at `session_projection.py:476-478` is deleted. False confidence in the branch. (i) Still no positive real-turn event test: the only quasi-real-turn test (`test_terminal_chat_loop.py::test_trimmed_history_keeps_tool_blocks_atomic`) does **not** trigger a compaction at all — instrumented probe shows `compact events: 0`; its `len(trimmed) < len(history)` assertion only reflects the final ASSISTANT message appended after the last provider call (14 vs 15), not a dropped turn. So no test drives ≥1 real drop and asserts exactly one `SESSION_CONTEXT_COMPACTED` event. (ii) `test_compaction_never_splits_a_tool_group` (`:169-182`) still asserts only `kept[-1].content == "u2"`; no tool-block-closure/orphan-TOOL assertion. |
| F8 | LOW | **CLOSED** | Key now includes `retained_digest` (`agent_loop.py:1561-1565`). `test_two_distinct_compactions_are_both_recorded` passes; independent probe: two distinct retained sets with identical `dropped_messages`/`kept_from_index` → **2** events recorded. |
| F9 | LOW (claim) | **CLOSED** | `goal-card-cp-ab.md:42-47` now says `(9)` and its 9-item list matches the shipped 9 tests exactly. |
| F10 | LOW (edge) | **CLOSED** | `if last_user == 0: return history, None` (`agent_loop.py:1600-1602`). Probe: no-USER history → `payload is None`, `kept == history` (no tail drop). |

## 2. New findings

| ID | Severity | Finding |
|----|----------|---------|
| F11 | **MED (regression — reopens F2)** | Binding the dedup key to `retained_digest` **reintroduces per-step event recording within a single turn**. The retained set is recomputed each provider step and grows as in-turn ASSISTANT/TOOL messages are appended, so the digest changes every step while `dropped_messages`/`kept_from_index` stay fixed. Real two-turn probe (`_todo_script`, budget 150): turn 2 completed in **2** steps and emitted **2** `SESSION_CONTEXT_COMPACTED` events with identical `(dropped=4, kept_from_index=5)` but different digests. Synthetic 6-step in-turn probe → **6** events. This contradicts the goal card §5 claim "events are bounded by turns, not steps" (`goal-card-cp-ab.md:57-58`), which is now false. Fix: key on the active-turn boundary (e.g. the `last_user` index / turn identity, or reset `_last_compaction` per turn) instead of, or in addition to, a digest that is stable across the turn; the retained digest should describe the retained set up to the active-turn boundary, not the ever-growing live history. `agent_loop.py:1561-1565` + `agent_loop.py:1621-1628`. |
| F12 | **LOW (doc/claim)** | `goal-card-cp-ab.md:57-58` still states the dedup key is `(dropped_messages, kept_from_index)` and "events are bounded by turns, not steps" — both now inaccurate (key is a 3-tuple; cardinality is per-step per F11). The §5 residual was not updated alongside §4. |

## 3. Required probes (step 2)

| Probe | Result |
|-------|--------|
| (a) dedup includes `retained_digest`, two distinct compactions both recorded | PASS — `test_two_distinct_compactions_are_both_recorded`; probe → 2 events |
| (b) no-USER history is a no-op | PASS — payload `None`, `kept == history` |
| (c) projection replay test genuine | **PARTIAL** — event written + projection succeeds, but the event omits `session_id` and is pre-filtered; the new branch is never exercised (test is vacuous w.r.t. the branch) |
| (d) active request never dropped / tool groups never split | PASS — probe kept `[SYSTEM, USER(active)]`, last content = active user, no orphan TOOL; `cut<=1` guard intact (`agent_loop.py:1617-1620`) |
| (e) determinism | PASS — cross-instance digest test (`:206-223`), 64-char sha256 |
| (f) no new bug (type / cardinality) | **type OK, cardinality FAIL** — `_last_compaction` init `None`, annotation `tuple[object, ...] | None`; but cardinality regresses per-step (F11) |

## 4. Test run

```
$ uv run --extra product-test pytest tests/product/test_context_compaction.py tests/product/test_session_projection.py -q
40 passed in 1.01s
```

Breakdown: `test_context_compaction.py` = 9 passed; `test_session_projection.py` = 31 passed.
Also: `ruff check ... agent_loop.py tests/product/test_context_compaction.py` → clean; `pyright ...` → 0 errors.

## 5. Required changes before promotion

1. **Fix F11** (blocking): do not key dedup on an ever-growing digest. Include the active-turn
   boundary (e.g. `last_user` / turn id) or reset the dedup slot per turn so exactly one event is
   recorded per turn, per the documented contract.
2. Add the missing positive real-turn event test: drive ≥2 turns through `run_turn` with a forced
   drop and assert exactly one `SESSION_CONTEXT_COMPACTED` event with `dropped_messages >= 1` and
   `chars_before > chars_after` (F7(i)). Note `test_trimmed_history_keeps_tool_blocks_atomic` does
   not currently trigger compaction and should not be counted as coverage.
3. Strengthen tool-group closure assertion in `test_compaction_never_splits_a_tool_group` (F7(ii)).
4. Either make the projection replay test exercise the branch (add `session_id` to the payload / call
   `_strict_project` directly) or delete the unreachable branch and rely on the documented pre-filter
   (F7(iii)); the current test advertises branch coverage it does not have.
5. Correct `goal-card-cp-ab.md:57-58` (F12) once F11 is fixed.

## 6. Independence limitation

The reviewing model is `deepseek-flash`, the **same model family as the builder**, so this is a
same-model review and does **not** satisfy the constitution's independent-reviewer identity
requirement (`builder_id != reviewed_by`). A different-provider reviewer remains required before
promotion.

---

**VERDICT: APPROVE_WITH_CHANGES**

- F7 **OPEN (partially)**; F8 CLOSED; F9 CLOSED; F10 CLOSED
- New: F11 **MED** (regression, reopens F2), F12 LOW (doc)
- Test counts: `test_context_compaction.py` 9 passed, `test_session_projection.py` 31 passed, combined 40 passed
