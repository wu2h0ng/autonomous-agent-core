# Independent Exact-Diff RE-REVIEW (R2) — M1 S4 Deterministic Context Compaction

> Fix commit under review: `3098ddbf`
> Parent: `62e47309`; base `origin/main`: `18d7b9b0`
> Worktree: `autonomous-agent-core/.worktrees/m1-danger-cmd-20260915`
> Prior report: `.agent_runs/m1-context-compaction-s4-20260915/review-subagent.md`
> Disposition: independent adversarial exact-diff re-review; source/tests read-only.
> Scope: Product Track, medium risk (Agent Core runtime / ProviderRequest path).

## 0. Diff reviewed

`git diff 62e47309..3098ddbf` touches only:

- `agent_loop.py`: dedup key `(dropped_messages, chars_after)` → `(dropped_messages, kept_from_index)`; empty/non-positive-budget guard in `_compact_history`; new `if cut <= 1: return history, None` no-op guard; `_history_digest` now binds `tool_call_id` + `tool_calls`.
- `session_projection.py`: explicit no-op branch for `SESSION_CONTEXT_COMPACTED` in `_strict_project`.
- `tests/product/test_context_compaction.py`: replaced the weak positive turn-path test with a single-turn no-event test + determinism test; assertions strengthened in two unit tests.
- `.agent_runs/.../goal-card-cp-ab.md`: §2/§5 wording corrected.

The authority-relevant `_call_provider` surface (`agent_loop.py:1153-1199`) is unchanged except that
`_maybe_record_compaction` is invoked between the binding/correction checks and the `ProviderRequest`
construction (`agent_loop.py:1188-1189`); `task_id`/`run_id`/`provider_profile_id`/
`allowed_capability_ids`/`timeout_seconds` are byte-identical. No authority widening.

## 1. Per-finding re-adjudication

| ID | Prior severity | Status | Evidence |
|----|----------------|--------|----------|
| F1 | MED | **CLOSED** | `if cut <= 1: return history, None` (`agent_loop.py:1610-1613`). Probe (a): `payload is None`, `kept == history`, `0` events recorded for a single over-budget turn. Integration `test_single_turn_records_no_compaction_event` passes. |
| F2 | MED | **CLOSED** | Dedup key is now `(dropped_messages, kept_from_index)` (`agent_loop.py:1561`). Probe (b1): 6 appends within one active turn (fixed `last_user`) → **exactly 1** event (was 4 per-step). |
| F3 | LOW-MED | **CLOSED (doc honesty)** | Behavior unchanged (active turn never dropped), but goal-card §5 now explicitly states `max_context_chars` is a soft target and single over-budget turns are kept in full (`goal-card-cp-ab.md:51-54`). Residual: the `_compact_history` docstring (`agent_loop.py:1575`) still says "compact history to max_context_chars"; cosmetic. |
| F4 | MED | **CLOSED** | Explicit `SESSION_CONTEXT_COMPACTED` no-op branch added (`session_projection.py:476-478`). Probe (d): projection succeeds both without `session_id` (implicit pre-filter) **and with `session_id`** (branch). Note: the branch is currently only reachable in the with-`session_id` case; the real payload still omits `session_id`, so it is defensive. No repo test replays a compacted session. |
| F5 | LOW | **CLOSED** | `_history_digest` now hashes `tool_call_id` and `tool_calls` (`agent_loop.py:1632-1640`). Probe (e): changing a `tool_call_id` changes the digest; identical histories match. |
| F6 | LOW | **CLOSED** | `if not history or self._config.max_context_chars <= 0: return history, None` (`agent_loop.py:1585-1586`). Probe (f): empty history + budget 0 → `([], None)`; only-system + tiny budget → `([sys], None)`; no `IndexError`. |
| F7 | LOW (tests) | **OPEN (partially)** | Improvements: `test_compaction_drops_oldest_turn_and_keeps_the_active_request` now asserts `dropped_messages >= 1`; a real cross-instance determinism test added. Still open: (i) the positive "event recorded on the real turn path" test was **deleted** and not replaced — the only remaining real-turn compaction test (`test_terminal_chat_loop.py:1682 test_trimmed_history_keeps_tool_blocks_atomic`) asserts on provider `messages`, not on the `SESSION_CONTEXT_COMPACTED` event; (ii) `test_compaction_never_splits_a_tool_group` still asserts only `kept[-1].content == "u2"` and does not assert tool-block closure; (iii) no test replays/projects a compacted session (F4). |

## 2. New findings

| ID | Severity | Finding |
|----|----------|---------|
| F8 | **LOW** | The new per-turn dedup key **under-records** genuine later compactions. `_last_compaction` is a single slot keyed only on `(dropped_messages, kept_from_index)`, which can coincide across two different turns while the retained set (and digest) differs. Probe (b2), same loop, budget 50: turn A → key `(2,3)` digest `89fb1515…`; turn B → key `(2,3)` digest `5ac734fb…`; only **1** event recorded. Fix: include the active-turn boundary (e.g. the `last_user` index / turn identity) in the key, which preserves one-event-per-turn and removes the collision. `agent_loop.py:1561-1564`. |
| F9 | **LOW (claim accuracy)** | The goal-card `## 4. Verification` block was not updated with §2/§5: it still says `(6)` tests and lists "the event is recorded on the real turn path" as a test, but that test was removed and the suite now has 7 tests. The section therefore overstates the current verification set (`goal-card-cp-ab.md:40-47`). |
| F10 | **LOW (edge, unreachable)** | With a history containing no USER message the cut loop no longer aligns to USER boundaries (`limit = len(history)`), so it silently drops the whole non-system tail and records a compaction with `dropped_messages >= 1` (probe (f) `no_user` → kept `[SYSTEM]`, dropped 2). Not reachable through the product path (`AgentLoop` seeds a leading SYSTEM then a USER), so it is a latent-only oddity; the `cut <= 1` guard does not cover it. |

## 3. Re-probe results (all required probes)

| Probe | Result |
|-------|--------|
| (a) no-drop over-budget eval | `payload is None`, `kept == history`, `0` events — PASS |
| (b) cardinality bounded by real drops | 1 event for 6 in-turn steps; cross-turn key-collision suppresses a distinct compaction (F8) — PASS on per-turn, new low defect |
| (c) active request / tool group | `[SYSTEM, USER]`, last `u2`, no orphan TOOL; `dropped_messages=3, kept_from_index=4` — PASS |
| (d) projection with / without `session_id` | both `ok` — PASS |
| (e) determinism / id binding | identical → equal digest; `tool_call_id` change → different digest — PASS |
| (f) empty / odd histories | empty+budget0 → `([], None)`; only-system → `([sys], None)`; large active turn → no crash, `None`; no-USER → drops tail (F10) — PASS (no crash) |

Additional: `tests/product/test_session_projection.py` → **31 passed**; `test_trimmed_history_keeps_tool_blocks_atomic` → 1 passed.

## 4. Test run

```
$ uv run --extra product-test pytest tests/product/test_context_compaction.py -q
.......                                                                  [100%]
7 passed in 0.66s
```

Target-suite count: **7 passed**.

## 5. Required changes before promotion

1. Add a real-turn-path positive test: drive ≥2 turns through `run_turn` and assert exactly one
   `SESSION_CONTEXT_COMPACTED` event with `dropped_messages >= 1` and `chars_before > chars_after`
   (restores the coverage the fix removed). Fixes F7(i)/F9.
2. Strengthen `test_compaction_never_splits_a_tool_group` to assert tool-block closure (reuse
   `_assert_tool_blocks_closed`) and no orphan TOOL anywhere in the retained list. Fixes F7(ii).
3. Add a resume/project test replaying a session that contains a compaction event (ideally with
   `session_id`) to exercise the new `session_projection` branch. Fixes F7(iii).
4. Key the dedup on the active-turn boundary as well, so two different turns cannot collapse to one
   event. Fixes F8.
5. Update goal-card `## 4` to match the shipped 7-test suite and remove the stale "recorded on the
   real turn path" line (or restore that test). Fixes F9.

Runtime behavior (F1-F6) is now correct; items 1-5 are test/doc completeness and one low-severity
dedup edge.

## 6. Independence limitation

The reviewing model is `deepseek-flash`, the **same model family as the builder**, so this is a
same-model review and does **not** satisfy the constitution's independent-reviewer identity
requirement (`builder_id != reviewed_by`). A different-provider reviewer remains required before
promotion.

---

**VERDICT: APPROVE_WITH_CHANGES**

- F1 CLOSED, F2 CLOSED, F3 CLOSED (doc), F4 CLOSED, F5 CLOSED, F6 CLOSED, F7 **OPEN (partially)**
- New: F8 LOW, F9 LOW (claim accuracy), F10 LOW (unreachable edge)
- Test count: 7 passed
