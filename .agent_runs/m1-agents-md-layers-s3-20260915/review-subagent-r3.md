# Independent Adversarial THIRD Exact-Diff Review — S3 Layered AGENTS.md/CLAUDE.md

- Reviewer: independent subagent, adversarial exact-diff review (source/tests READ-ONLY)
- Worktree: `autonomous-agent-core/.worktrees/m1-danger-cmd-20260915`
- Fix commit under review: `53d783d6` (parent `10cb50ae`; base `origin/main` `18d7b9b0`)
- Prior reports: `review-subagent.md` (initial, `21c20246`), `review-subagent-r2.md` (`10cb50ae`)
- Files inspected: `packages/os_core/src/agent_os_core/agent_context.py`, `apps/api_server/app.py`, `packages/os_core/src/agent_os_core/__init__.py`, `tests/product/test_agents_markdown_layers.py`, `tests/product/test_chat_agents_markdown.py`, goal card `goal-card-cp-ab.md`
- Method: `git diff 10cb50ae..53d783d6`, full read of the module, and adversarial execution probes under `uv run --extra product-test` (5000/20000/25000/50000-entry single dirs, 300-dir fan-out, 60k total entries, O_NOFOLLOW boundary/symlink/oversize with instrumented `os.read`, legacy `discover_agents_markdown` on 200 KB and 20 KB, `st_ino==0` forced via `Path.stat` patch, hardlink dedupe, nested-only/root-CLAUDE/nested-CLAUDE/bad-root provenance, 10× determinism, caps)

## Verdict

**APPROVE_WITH_CHANGES**

The four substantive fixes landed and are verified by code + executable probes: N1's defect (full-dir sort/materialization), F4 (symlink→read TOCTOU), N4 (legacy unbounded read), and N2 (`st_ino==0` false dedupe) are all CLOSED. No regression in ordering, provenance, digest identity, caps or fail-closed behavior. However N5 (the 128 KiB cap documentation requested in r2) is NOT addressed, and the new fix ships a **dead `_MAX_ENTRIES_PER_DIR` constant** whose claimed per-directory cap is not implemented, plus a test that does not exercise the entry budget. These are documentation/claim-integrity and test-validity issues, not runtime authority or correctness defects — hence APPROVE_WITH_CHANGES, not NO_APPROVE.

---

## Per-finding verification

### N1 — MEDIUM: loose-cased fallback sorted/materialized whole directories — **CLOSED**
`_pick` (`agent_context.py:154-176`) no longer calls `sorted(directory.iterdir())`. It uses `os.scandir` and materializes only actual matches (`matches` list); a shared `budget` counter is incremented per entry and the scan aborts once `budget[0] > max_entries` (`:165-167`). `os.walk` also breaks on the global budget (`:215`). Probes:
- 5000-entry dir, no instruction → 0 layers, **0.0088s**.
- 300 dirs × 200 entries (60k total) → 0 layers, **0.0462s**.
- 20000 / 25000 / 50000-entry single dir → **0.024s / 0.031s / 0.058s**, i.e. cost saturates at the ~20k global budget, not at directory size.
The unbounded per-directory *sort/materialization* cost is gone; total work is globally bounded. N1 CLOSED. Residuals are new findings N6/N8 below.

### F4 — LOW: symlink→read TOCTOU — **CLOSED**
`_read_bounded` (`agent_context.py:92-122`) now opens with `os.O_RDONLY | os.O_NOFOLLOW` and loops reads to the cap+1. Probes:
- exact 131072 bytes → accepted; 131073 → `None`; instrumented `os.read` read exactly **131073** bytes onto the oversize file (never the full file).
- in-workspace symlink, out-of-workspace symlink, dangling symlink → all `None`; `_read_layer` on a symlink → `None`.
Both the legacy (`:70`) and layered (`:137`) paths route through it, so the previous check-then-`open` window is closed for the final path component. CLOSED.

### N4 — LOW: legacy `discover_agents_markdown` unbounded read — **CLOSED** (with a behavior change, see N9)
`discover_agents_markdown` (`:51-85`) now uses `_read_bounded` instead of `read_text`. Probe: a 200 000-byte `AGENTS.md` returns `None` (bounded); a 20 000-byte file returns 12 000 chars, `truncated=True`, sha256 over the full content. CLOSED as a resource fix.

### N2 — LOW: `st_ino==0` false dedupe — **CLOSED**
Dedupe (`:231-236`) now only inserts/consults the `(st_dev, st_ino)` key when `stat.st_ino != 0`; the key is added only after a successful `_read_layer` in the previous commit and the skip-on-zero cannot collapse distinct files. Probe with `Path.stat` patched to return `st_ino==0`: two distinct nested `AGENTS.md` → `['a/AGENTS.md', 'b/AGENTS.md']` (both preserved). Hardlink dedupe still works when `st_ino!=0` → `['one/AGENTS.md']`. CLOSED.

### N5 — LOW/INFO: undocumented 128 KiB cap — **OPEN**
The r2 request was to *document* the cap. The value still appears only in the code comment (`agent_context.py:28`) and is absent from the goal card (`goal-card-cp-ab.md:17-20` lists the signature without the byte cap, `max_dirs`, or `max_entries`) and from the public function docstring (which says "oversized ... skipped silently" without the 128 KiB figure). No test covers the 128 KiB→`max_chars` band. OPEN (documentation only).

---

## New findings

### N6 — LOW (claim integrity / dead code): `_MAX_ENTRIES_PER_DIR = 500` is defined but never used
`agent_context.py:29` defines the constant; it is referenced nowhere in the repo (grep: 1 occurrence = the definition). The "per-directory entry cap" named in the fix description therefore does **not** exist; only the global `max_entries=20000` budget is real. A 5000-entry directory is still scanned end-to-end (bounded and cheap, but contradicting the stated control). Fix: either enforce it in `_pick` (`if scanned_in_dir > _MAX_ENTRIES_PER_DIR: break`) or delete the constant so the code does not assert a control it lacks.

### N7 — LOW (test validity): `test_huge_directory_is_bounded` does not test the entry budget
`tests/product/test_agents_markdown_layers.py:63-71` puts an exact-case `AGENTS.md` in the big directory. `_pick` short-circuits on `candidate.is_file()` (`:155-158`) and never enters the loose-cased scan, so the 3000 sibling entries and `max_entries` are never exercised. The test passes for the wrong reason and would not fail if the budget logic were removed. Add a directory with >`max_entries` loose-cased-free entries (e.g. call `discover_agents_markdown_layers(tmp_path, max_entries=50)` with 500 files and assert no stall/no loose match) to actually bind the budget.

### N8 — LOW (design note): global budget is consumed by instruction-free loose-cased scans and can starve nested discovery
The shared `budget` is incremented for every entry in every loose-cased fallback scan, including directories with no instruction file. A workspace whose root (or first-walked dirs) contains ≥20000 unrelated entries exhausts the budget before nested directories are visited, so legitimate nested layers are silently skipped. This is a deliberate bound, but the interaction is untested and undocumented; consider documenting it (N5) or resetting the budget per directory (N6).

### N9 — LOW (behavior change to exported public API): legacy `discover_agents_markdown` now refuses >128 KiB instead of truncating
Previously the legacy single-file function read the full file and returned a truncated context (digest over full content). After N4's fix it returns `None` for any file >128 KiB (probe confirmed). It is still exported (`__init__.py:195,514`). This is arguably consistent with the layered path, but it silently drops previously-working large root files and is undocumented. Record as accepted or document the cap/cliff in the function docstring.

### N10 — INFO (residual): intermediate-path-component TOCTOU and legacy resolver readdir remain
`O_NOFOLLOW` only guards the final component; `_read_bounded` would still follow a symlinked *intermediate* directory swapped after `_read_layer`'s `resolve()`/`relative_to()` check (`:132-136`). Not reachable through `os.walk(followlinks=False)` in normal traversal, so theoretical/defense-in-depth only. Separately, `_resolve_agents_markdown_path` (`:40-48`) still does an unbounded `root.iterdir()` (O(n), no sort/materialization) on the legacy path. Both are low/informational.

---

## Regression probes that passed (non-findings)

- **Provenance/labels**: nested-only → `# Nested AGENTS.md (path=pkg/AGENTS.md, ...)`, no `Project`; root `CLAUDE.md` → `# Project CLAUDE.md`; nested `CLAUDE.md` → `# Nested CLAUDE.md`; non-UTF-8 root + valid nested → nested correctly labels as `Nested` (old F1 bug gone).
- **Root-only byte-identity**: `layered_agents_markdown_system_section` == `agents_markdown_system_section` and identical sha256.
- **Fail-closed**: symlink→outside, dangling, non-UTF-8 root/nested, empty/nonexistent workspace → no exception, skipped silently.
- **Determinism**: 10 repeated scans of a mixed tree → single identical order.
- **Caps**: `max_layers=2` → 2; `max_total_chars=150` → exactly 150 across 2 layers.
- **Ordering**: deterministic `a/AGENTS.md, a/z/AGENTS.md, a-b/AGENTS.md, a1/AGENTS.md` (depth-first per-dir sort; documented behavior note from r2 stands).
- **Explicit `loop_config` still wins**; app.py docstring correctly describes the layered/bounded/fail-closed behavior.
- **Ruff**: `All checks passed!`; **Pyright** on `agent_context.py`: `0 errors, 0 warnings, 0 informations`.

---

## Test run

```
uv run --extra product-test pytest tests/product/test_agents_markdown_layers.py tests/product/test_chat_agents_markdown.py -q
.....................                                                    [100%]
21 passed in 1.75s
```

Counts: **21 passed, 0 failed** = 16 in `test_agents_markdown_layers.py` (14 prior + 2 new: `test_loose_cased_name_is_found`, `test_huge_directory_is_bounded`) + 5 in `test_chat_agents_markdown.py`. No failures; ruff clean; pyright 0. Coverage gaps: no real entry-budget test (N7), no `st_ino==0` test (N2 verified only by probe), no 128 KiB-band test, no per-dir-cap test (N6 constant unused).

---

## Required changes before promotion

1. **N6 (LOW)**: enforce `_MAX_ENTRIES_PER_DIR` in `_pick` or delete it — do not ship a constant that claims a control the code lacks.
2. **N5 (LOW)**: document the 128 KiB per-file cap (and `max_dirs`/`max_entries`) in the goal card and/or public docstring.
3. **N7 (LOW)**: add a test that actually binds the entry budget.
4. **N8/N9 (LOW)**: document the budget-starvation and legacy-oversize-refusal behaviors, or record them as accepted with dated rationale.

None of these change authority, C7, permissions, or the correctness of the prompt-context injection.

## Independence limitation

The builder, the prior reviewers, and this reviewer share the same underlying model family/provider (this is the third review by the same model). Independence is limited to the role/prompt, read-only constraint and the executable evidence chain — it is not a genuinely different model. It therefore cannot by itself satisfy RR-0024/RR-0031 independent-review identity for any claim beyond prompt-context behavior; a provider-independent reviewer is required before promotion beyond S3 prompt-context.

## Verdict

**APPROVE_WITH_CHANGES**
