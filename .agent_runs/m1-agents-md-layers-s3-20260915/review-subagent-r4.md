# Independent Adversarial FOURTH Exact-Diff Review — S3 Layered AGENTS.md/CLAUDE.md

- Reviewer: independent subagent, adversarial exact-diff review (source/tests READ-ONLY)
- Worktree: `autonomous-agent-core/.worktrees/m1-danger-cmd-20260915`
- Fix commit under review: `efee61c3` (parent `53d783d6`; base `origin/main` `18d7b9b0`)
- Prior reports: `review-subagent.md` (`21c20246`), `review-subagent-r2.md` (`10cb50ae`), `review-subagent-r3.md` (`53d783d6`)
- Files inspected: `packages/os_core/src/agent_os_core/agent_context.py`, `tests/product/test_agents_markdown_layers.py`, `tests/product/test_permission_deny_rules.py`, goal card `goal-card-cp-ab.md`
- Method: `git diff 53d783d6..efee61c3`, full module read, executable probes (legacy oversize truncation, 3-byte char straddling the 128 KiB cap, invalid-UTF-8 + oversize, digest-collision beyond cap, 3000/600-entry dirs, provenance/ordering/fail-closed), `ruff`, `pyright`, and the two required pytest files

## Verdict

**APPROVE_WITH_CHANGES**

The requested fixes for N9, N5 and N6 landed and are verified. N9 legacy now truncates instead of returning `None`; N5 bounds are documented in goal card §5; N6 `_MAX_ENTRIES_PER_DIR` is now actually enforced in `_pick` (`agent_context.py:171`). No correctness, authority, C7 or fail-closed regression was found for the layered path; the root-only byte-identity renders identically. However N7 and N8 remain OPEN: the "huge directory" test still passes for the wrong reason, and the global entry-budget starvation path is still untested (the goal card even mis-cites a `max_entries=0` test that does not exist). New LOW-severity issues NF2/NF3 concern the legacy oversize decode semantics. These are test-validity / claim-integrity issues, not runtime-authority defects — hence APPROVE_WITH_CHANGES, not NO_APPROVE.

## Per-finding verification

### N6 — LOW: `_MAX_ENTRIES_PER_DIR` defined but unused — **CLOSED**
`agent_context.py:29` `_MAX_ENTRIES_PER_DIR = 500` is now consumed in `_pick`:
`:170 for index, entry in enumerate(iterator):` and `:171-172 if index >= _MAX_ENTRIES_PER_DIR: break`. `rg` shows the constant is referenced at the definition and at `:171` only. The per-directory cap is applied to the loose-cased fallback scan (exactly the scope the comment names); the exact-case `candidate.is_file()` probe stays O(1). CLOSED.

### N7 — LOW: huge-dir test passed for the wrong reason — **OPEN**
`test_huge_directory_does_not_stall` (`tests/product/test_agents_markdown_layers.py:63-71`, only renamed) still creates `big/AGENTS.md` as an exact-case file. `_pick` (`:161-164`) returns at `candidate.is_file()` before the `os.scandir` loop is ever entered, so the 3000 sibling files and both budget counters are never exercised; the test would still pass if all budget logic were deleted. The new `test_directory_budget_stops_nested_traversal` (`:74-81`) binds `max_dirs`, not the entry scan/cap. No test passes `max_entries`. Wrong-reason condition persists → OPEN.

### N8 — LOW: global entry budget can starve nested discovery, untested/undocumented — **OPEN (doc landed, test does not)**
Goal card §6 (`goal-card-cp-ab.md:53-54`) now documents the starvation interaction, but claims it is "tested via `max_entries=0`". No test in the repo passes `max_entries` (rg: only `max_dirs=0` at `test_agents_markdown_layers.py:80`). The global-budget branch `budget[0] > max_entries` (`agent_context.py:174,223`) remains unexercised and the doc mis-cites the test. → OPEN.

### N9 — LOW: legacy `discover_agents_markdown` returned None for >128 KiB instead of truncating — **CLOSED**
`discover_agents_markdown` (`:70-88`) now consumes `_read_bounded`'s `(data, oversized)` and truncates. Probe: a 131 072+100-byte file returns a context with `truncated=True` (not `None`); a `€` (3-byte) character straddling byte 131072 does not raise; the layered path still rejects oversize (`_read_layer:143-145`). CLOSED, with NF2/NF3 residuals below.

### N5 — 128 KiB cap undocumented — **CLOSED**
Goal card §5 (`:41-47`) now states the per-file 128 KiB hard cap, layered-skip vs legacy-truncate semantics, the 500-entry per-dir cap, and the 20 000-entry / 2 000-dir global budget. Residual (non-blocking): the public `discover_agents_markdown` docstring still omits the figure and goal card §2's signature still omits `max_dirs`/`max_entries`. Documentation intent satisfied → CLOSED.

## New findings

### NF1 — LOW (claim integrity): goal card mis-cites a nonexistent test
`goal-card-cp-ab.md:54` says starvation is "tested via `max_entries=0`", but the only new budget test uses `max_dirs=0` (`test_agents_markdown_layers.py:80`); no test passes `max_entries`. The cited evidence does not exist.

### NF2 — LOW (fail-closed weakening, broader than claimed): legacy oversize decode ignores ALL invalid UTF-8, not just a split boundary char
`agent_context.py:77` uses `errors="ignore" if oversized else "strict"` over the whole first 128 KiB. Probe: an oversize file with `\xff\xfe` in the middle returns a context (invalid bytes silently dropped), whereas the same bytes in a small file correctly return `None`. The comment at `:74-75` claims only a byte-cap boundary split is tolerated; the actual tolerance is file-wide. Layered path still fails closed (`strict`).

### NF3 — LOW (digest semantics): legacy oversize digest now collides beyond the cap
For oversize files the digest is over only the first 128 KiB (ignore-decoded). Probe: `b"x"*131072 + b"A"` and `b"x"*131072 + b"B"` produce identical `sha256`. Previously the legacy digest covered the full decoded file; because content is also truncated to `max_chars`, the digest was the sole full-file change signal and is now bounded. Acceptable given the hard cap, but should be recorded/asserted.

### NF4 — LOW (scope/test hygiene): unrelated timeout loosening bundled into the fix commit
`tests/product/test_permission_deny_rules.py` changes `_wait_for` default timeout `5.0 -> 20.0`s (4×). Unrelated to S3; loosening this default can mask real hangs/slow regressions in the permission-deny suite. Should be split out or justified.

### NF5 — INFO (doc staleness): goal card §4 says the test file has "(9)" tests (actual 17); §2 signature predates `max_dirs`/`max_entries`; §4's "23 failed == base" was not re-run here.

### NF6 — INFO: per-dir cap silently misses a loose-cased instruction file past the 500th scandir entry — intended (comment `:165-166`) but untested.

## Regression probes that passed (non-findings)

- Root-only digest identity (`discover_agents_markdown` == layered[0] sha256) and render identity (`layered_agents_markdown_system_section` == legacy section) — True.
- Ordering: `AGENTS.md, a/AGENTS.md, a/z/AGENTS.md, a-b/AGENTS.md, a1/AGENTS.md, b/AGENTS.md` (depth-first, per-dir sorted).
- Fail-closed: symlinked nested layer → `()`; non-UTF-8 file → `()`.
- Bounded read: `_read_bounded` reads at most cap+1 (never full file); all callers updated to the tuple return.
- `ruff`: All checks passed. `pyright` on the module: 0 errors/warnings/informations.

## Test run

```
uv run --extra product-test pytest tests/product/test_agents_markdown_layers.py tests/product/test_chat_agents_markdown.py -q
......................                                                   [100%]
22 passed in 0.90s
```

Counts: **22 passed, 0 failed** = 17 in `test_agents_markdown_layers.py` + 5 in `test_chat_agents_markdown.py`. Coverage gaps: no test passes `max_entries` (N8/NF1), no test binds the entry cap or the loose-cased scan on a huge dir (N7), no 128 KiB boundary/oversize-truncation test in either legacy or layered path, no test for the invalid-UTF-8-oversize behavior (NF2).

## Required changes before promotion

1. **N7 (LOW)**: make the huge-dir test exercise the loose-cased scan/entry budget (e.g. `max_entries=0`/small cap with >cap non-matching entries) so it fails if the budget is removed.
2. **N8/NF1 (LOW)**: add a real `max_entries` test and correct the goal card citation.
3. **NF2 (LOW)**: restrict the legacy oversize tolerance to the trailing boundary or document the file-wide `errors="ignore"` behavior.
4. **NF3 (LOW)**: record the capped legacy digest (collision beyond 128 KiB) as accepted with rationale.
5. **NF4 (LOW)**: unbundle/justify the `_wait_for` timeout change.

None of these change authority, C7, permissions, or the correctness of the prompt-context injection.

## Independence limitation

This is the fourth review by the same underlying model family/provider as the builder and prior reviewers; independence is limited to role/prompt, the read-only constraint, and the executable evidence chain. It cannot by itself satisfy RR-0024/RR-0031 independent-review identity beyond prompt-context behavior; a provider-independent reviewer is required before promotion beyond S3 prompt-context.

## Verdict

**APPROVE_WITH_CHANGES**
