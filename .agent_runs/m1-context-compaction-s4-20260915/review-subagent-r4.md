# Independent Exact-Diff RE-REVIEW (R4) — M1 S4 Deterministic Context Compaction

> Fix commit under review: `96c6cd32` (parent `1f85bc9f`; base `origin/main` `18d7b9b0`)
> Worktree: `autonomous-agent-core/.worktrees/m1-danger-cmd-20260915`
> Prior reports: `.agent_runs/m1-context-compaction-s4-20260915/review-subagent.md`,
> `review-subagent-r2.md`, `review-subagent-r3.md`
> Disposition: independent adversarial exact-diff fourth review; source/tests treated READ-ONLY.
> Scope: Product Track, medium risk (Agent Core runtime / ProviderRequest path).

## 0. Diff reviewed

`git diff 1f85bc9f..96c6cd32` (the range includes docs commit `03d7ae76`) touches only:

- `packages/os_core/src/agent_os_core/agent_loop.py`:
  - dedup key `(dropped_messages, kept_from_index, retained_digest)` → `(dropped_messages, kept_from_index)` at `agent_loop.py:1564`, with a new comment at `:1561-1563`.
- `tests/product/test_context_compaction.py`:
  - new `test_two_turns_compact_once_over_the_turn_path` (`:197-207`);
  - `test_projection_ignores_a_recorded_compaction` now injects `"session_id"` so the event reaches the explicit projection branch (`:266`);
  - `test_two_distinct_compactions_are_both_recorded` now uses two *different* boundaries (`:273-286`);
  - new `test_same_boundary_is_recorded_once_across_steps` (`:289-297`).
- `.agent_runs/.../goal-card-cp-ab.md`: §4 count changed `6→9` (from `03d7ae76`) and §5 key wording updated in `96c6cd32`.
- `.agent_runs/.../review-subagent-r3.md`: prior report committed.

No change to the authority surface (`ProviderRequest` field binding byte-identical), permissions,
C7, or capability semantics. `ruff` clean; `pyright` 0 errors on the two touched files.

## 1. Per-finding adjudication

| ID | Task severity | Status | Evidence |
|----|---------------|--------|----------|
| F11 | MED (regression) | **PARTIALLY CLOSED** | The named regression is fixed: keying on the drop boundary removes the digest-per-step churn. Real 2-turn path (`_todo_script`, budget 120) now records **exactly 1** event; the old digest key yields **2** (verified by monkeypatching the old key and re-running `test_two_turns_compact_once_over_the_turn_path` → FAIL, and with dedup removed → FAIL). **Residual (see F13):** the boundary is *not* guaranteed stable across the steps of one turn; a real multi-step turn can still emit more than one event. |
| F7 | LOW | **CLOSED** | (i) `test_two_turns_compact_once_over_the_turn_path` (`:197-207`) drives two real `begin_turn` calls and asserts `len(events)==1`, `dropped_messages>=1`, 64-char digest. Instrumented real path: turn 1 emits 0, turn 2 emits 1 with `dropped_messages=4`, `chars_before=180 > chars_after=46`. It is bypass-detecting (fails under both the old digest key and no dedup). (ii) The projection test now carries `session_id`, so `project_session` includes the event at `session_projection.py:227` and `_strict_project` reaches the explicit branch `:476-478`; with that branch deleted the event falls through to `raise ... "unsupported session event"` at `:551`. Branch is genuinely exercised. |
| F12 | LOW (doc/claim) | **OPEN** | §4 heading still says `(9)` and lists 9 tests, but the file now ships **11** test functions — the two tests added by this commit (`test_two_turns_compact_once_over_the_turn_path`, `test_same_boundary_is_recorded_once_across_steps`) are not counted or listed. §5's new sentence "this is one event per real turn-level compaction, not per provider step" is contradicted by F13. The 2-tuple key wording itself is now correct. |

## 2. Required probes (step 2)

| Probe | Result |
|-------|--------|
| (a) drop-boundary key → one event per turn, later compactions still recorded | **PARTIAL.** Later/different boundaries are recorded (`test_two_distinct_compactions_are_both_recorded`; cross-turn real path records one per compacting turn). But "one per turn" fails in the boundary-advance case (F13): 3-turn real-path probe emitted 2 events for turn 3. |
| (b) two-turn turn-path test drops ≥1 and is genuine | **PASS.** Real path drops 4 messages; test FAILS with the old digest key and FAILS with dedup removed (regression/bypass-detecting). |
| (c) projection replay test reaches the explicit branch | **PASS.** With `session_id` present, the event survives the scope pre-filter and hits `:476-478`; removing the branch would raise at `:551`. (Note: production payloads have no `session_id`, so the branch remains unreachable for real events — F14.) |
| (d) active request never dropped / tool groups never split | **PASS.** Probe `[SYSTEM, USER(u1), ASSISTANT, TOOL, USER(u2)]` → kept `[SYSTEM, USER(u2)]`, no orphan TOOL, active user retained. Cut only ever lands on a USER index or `limit=last_user`; `cut<=1` guard intact (`:1616-1619`). |
| (e) determinism | **PASS.** `_history_digest` is sha256 over role/tool-call-id/tool_calls/content; cross-instance test `test_compaction_digest_is_deterministic` (`:219-236`) passes. |
| (f) no new bug | **Mostly PASS.** `_last_compaction` init `None`, annotation `tuple[object, ...] | None` (`:275`), only referenced in `_maybe_record_compaction`. Token/authority path unchanged. Residual cardinality issue = F13. |

## 3. New findings

| ID | Severity | Finding |
|----|----------|---------|
| F13 | **LOW (F11 residual)** | The drop boundary can advance *within* one turn, so `(dropped_messages, kept_from_index)` is not stable across a multi-step turn. Cause: `chars_before` grows as the active turn appends ASSISTANT/TOOL content, so the cut can move forward (never backward) toward `limit=last_user`; when the retained set at an earlier boundary exceeds budget on a later step, `cut` advances and a second, different key is recorded. **Real-path reproduction (worktree code, `_todo_script`-style):** a 3-turn script (budget 80) where turn 3 spans 2 provider steps recorded `(dropped=4, kept_from_index=5)` then `(dropped=6, kept_from_index=7)` — i.e. **2 events for one turn** (loop id identical for both calls). This contradicts the new code comment "recorded once per turn" (`agent_loop.py:1561-1563`) and goal-card §5. Impact is claim/cardinality, not authority or data loss (both events describe genuinely-applied compactions). Fix if strict one-per-turn is wanted: include turn identity / `last_user` (or reset per turn) in the dedup key, as R3 recommended. |
| F14 | INFO | Real `SESSION_CONTEXT_COMPACTED` payloads carry no `session_id` (probe: keys = `chars_after, chars_before, dropped_messages, kept_from_index, retained_digest`), so `project_session` filters them at `:227` and the branch at `:476-478` is unreachable for production events. The replay test therefore covers the branch only via a synthetic payload. Acceptable as defensive coverage, but the branch is effectively dead code in production. |

## 4. Test run

```
$ uv run --extra product-test pytest tests/product/test_context_compaction.py tests/product/test_session_projection.py -q
42 passed in 1.08s
```

Breakdown: `test_context_compaction.py` = **11 passed**; `test_session_projection.py` = **31 passed**.
`ruff check ... agent_loop.py tests/product/test_context_compaction.py` → clean;
`pyright ... agent_loop.py tests/product/test_context_compaction.py` → 0 errors, 0 warnings.

## 5. Required changes before promotion

1. **F12 (blocking, doc):** correct goal-card §4 to `(11)` and list the two new tests; adjust §5
   wording so it does not assert an absolute "one event per turn" (or fix F13 so the assertion holds).
2. **F13 (recommended):** if one-event-per-turn is the contract, key dedup on turn identity /
   `last_user` in addition to the boundary, and add a regression test for a multi-step turn whose
   boundary advances. Otherwise, soften the code comment and goal-card claim to "one event per
   distinct drop boundary".
3. Existing coverage gap from R3 F7(ii) remains a nit: `test_compaction_never_splits_a_tool_group`
   still asserts only `kept[-1].content == "u2"`; the independent probe confirms no orphan TOOL, but
   an explicit closure assertion would harden it.

## 6. Independence limitation

The reviewing model is `deepseek-flash`, the **same model family as the builder**, so this is a
same-model review and does **not** satisfy the constitution's independent-reviewer identity
requirement (`builder_id != reviewed_by`). A different-provider reviewer remains required before
promotion.

---

**VERDICT: APPROVE_WITH_CHANGES**

- F7 **CLOSED**; F11 **PARTIALLY CLOSED** (digest regression fixed; residual = F13); F12 **OPEN**
- New: F13 **LOW** (F11 residual / claim), F14 **INFO**
- Test counts: `test_context_compaction.py` 11 passed, `test_session_projection.py` 31 passed, combined 42 passed
