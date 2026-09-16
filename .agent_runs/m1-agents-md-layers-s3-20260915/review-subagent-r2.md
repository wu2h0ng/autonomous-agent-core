# Independent Adversarial RE-REVIEW (Exact-Diff) — S3 Layered AGENTS.md/CLAUDE.md

- Reviewer: independent subagent, adversarial exact-diff re-review (read-only on source/tests)
- Worktree: `autonomous-agent-core/.worktrees/m1-danger-cmd-20260915`
- Fix commit under review: `10cb50ae` (parent `21c20246`; base `origin/main` `18d7b9b0`)
- Prior report: `.agent_runs/m1-agents-md-layers-s3-20260915/review-subagent.md` (verdict APPROVE_WITH_CHANGES)
- Files inspected: `packages/os_core/src/agent_os_core/agent_context.py`, `apps/api_server/app.py`, `tests/product/test_agents_markdown_layers.py`, `tests/product/test_chat_agents_markdown.py`, goal card `goal-card-cp-ab.md`
- Method: `git diff 21c20246..10cb50ae`, full read of the module, and adversarial execution probes (nested-only, root CLAUDE.md, root byte-identity, non-UTF-8 root+nested, symlink in/out/dangling, hardlink, 10k node_modules tree, 3000-dir budget, 50k-entry dir, 2000×500 entry tree, oversized read accounting, capped boundary bytes, 10× determinism, depth-first vs global ordering)

## Verdict

**APPROVE_WITH_CHANGES**

F1, F2 (tree vector), F3, F5, F6, F7 are CLOSED and verified by both code and executable probes. F4 remains OPEN (LOW, defense-in-depth, was optional in the prior review). One residual resource defect (N1, MEDIUM) survives the F2 fix: directory-entry count is not budgeted. No authority/C7/permission change; correctness of the new labeling is sound.

---

## Per-finding re-verification

### F1/F7 — first layer label — **CLOSED**
`_layer_header` (`agent_context.py:203-207`) now derives the filename label (`AGENTS.md`/`CLAUDE.md`) from the actual basename and uses nested form iff the relative path contains `/`. Probes:
- nested-only `pkg/AGENTS.md` → `# Nested AGENTS.md (path=pkg/AGENTS.md, ...)`, no `Project`.
- root `CLAUDE.md` → `# Project CLAUDE.md`.
- root `AGENTS.md` + nested → root is `Project`, nested is `Nested`.
- failed root (non-UTF-8) + valid nested → nested rendered as `Nested` with `path=`, i.e. the old "promoted nested" bug is gone.
- nested `pkg/CLAUDE.md` → `Nested CLAUDE.md`.

The `"/" in path` inference is equivalent to a root marker on POSIX and on Windows (`as_posix()`): a root-adjacent file is always a single path component and a nested file always contains a separator. No false root/nested classification found. (An explicit `is_root` field would be more legible, but the heuristic is correct.)

### F2 — unbounded tree scan — **CLOSED** (with residual N1 below)
`root.rglob("*")` is replaced by `os.walk(root)` with in-place `dirs[:]` pruning of `_SKIP_DIRS` and dot-dirs (`agent_context.py:162-176`), plus a `max_dirs=2000` budget. Probes:
- 10k files in `node_modules` → **0.0003s**, one layer (root). Heavy dir never entered.
- 3000 instruction dirs → bounded by `max_layers`; ~0.11s.
- `.git`/`.hidden`/deep `a/.git` pruned; `a/b/AGENTS.md` kept.
- `os.walk(followlinks=False)` confirmed: an in-workspace dir symlink is not traversed (the real dir is still found directly).
The specific prior break tree (full-tree rglob into `.git`/`node_modules`) no longer costs anything.

### F3 — unbounded read — **CLOSED**
`_read_layer` now opens `"rb"` and reads at most `_MAX_BYTES_PER_FILE + 1` (131073) bytes; `> _MAX_BYTES_PER_FILE` (131072) is refused (`agent_context.py:100-108`). Probe with an instrumented `Path.open("rb")`: a 200 000-byte file caused exactly **131 073 bytes** read (not the full file) and returned no layer. Boundary exact: 131072 kept, 131073 refused. Digest is still over the full decoded text for accepted files, and the root-only case remains byte-identical to legacy (`legacy_digest_matches_discover_legacy: True`), so the digest contract is preserved for files ≤ cap.

### F4 — symlink TOCTOU — **OPEN (LOW)**
Unchanged: `is_symlink()` + `resolve()`/`relative_to()` are checked, then a separate `path.open("rb")` follows any symlink substituted between the check and the open. No `O_NOFOLLOW`/fd-based read. Requires a local concurrent swap of a caller-supplied workspace; defense-in-depth only, matching the prior LOW rating. Non-blocking but not closed.

### F5 — hardlink dedup — **CLOSED**
Dedup now keys on `(st_dev, st_ino)` (`agent_context.py:184-189`). Probe: two hardlinked `AGENTS.md` (same inode, different paths) → only `one/AGENTS.md` retained. Key is added only after a successful read, so a fail-closed first encounter does not mask a readable later path.

### F6 — stale docstring — **CLOSED**
`_loop_config_with_agents` (`app.py:207-213`) now documents the layered API, fail-closed causes incl. oversized, and the no-op case. Matches behavior.

### F7 — root CLAUDE.md header — **CLOSED** (see F1).

---

## Additional probes that passed (non-findings)

- **Fail-closed**: symlink→outside, dangling symlink, non-UTF-8 root, non-UTF-8 nested, empty workspace, nonexistent workspace all → `()`; no exceptions.
- **Determinism**: 10 repeated scans of a mixed tree gave an identical tuple order every time.
- **Caps**: `max_layers` and `max_total_chars` honored; root-only render is byte-identical to `agents_markdown_system_section`; explicit `loop_config` still wins.
- **Ruff** clean; **pyright** 0 errors / 0 warnings on `agent_context.py`.

---

## New findings

### N1 — MEDIUM (residual F2): directory-entry count is not budgeted; `_pick` sorts/materializes every scanned directory
`max_dirs` bounds directories visited, but not entries per directory. `_pick` calls `sorted(directory.iterdir())` (`agent_context.py:123-135`) whenever a directory has no exact-case `AGENTS.md`/`CLAUDE.md` — i.e. for the great majority of directories. Measured on this machine:
- one directory with 50 000 entries → **0.54s**;
- 2000 dirs × 500 entries (1M entries, zero instruction files) → **18.4s** in a single `discover_agents_markdown_layers` call.

`_loop_config_with_agents` invokes this synchronously on every chat-session open (`app.py:214`), and `workspace` is caller-supplied → avoidable latency/DoS and per-dir `Path` allocation on entry-heavy but directory-bounded trees. The original F2 text explicitly allowed "a directory/**entry** scan budget"; only the directory half landed. Suggested change (cheap, semantics-preserving): cap entries examined per directory (e.g. read a bounded prefix of a scandir/`islice` before falling back to sorted match, or refuse the case-insensitive fallback beyond N entries) and/or short-circuit once enough readable candidates exist. Add an entry-heavy regression test.

### N2 — LOW (portability regression introduced by the F5 fix): `(st_dev, st_ino)` can falsely collapse distinct files
On filesystems that report `st_ino == 0` (some FUSE/network mounts; historically Windows), all files on the same device share `(st_dev, 0)` and only the first layer survives — silently dropping legitimate distinct nested layers. The previous `path.resolve()` key could not do this. Likelihood is low; consider falling back to the resolved path when `st_ino == 0`.

### N3 — LOW/INFO: nested ordering is depth-first, not the legacy global path sort
Legacy used `sorted(root.rglob("*"))` (global lexicographic). The new walk emits depth-first with per-directory sort, so e.g. for `a/`, `a/z/`, `a-b/`, `a1/` the order is `a/z`, `a-b`, `a1` vs. legacy `a-b`, `a/z`, `a1`. It is deterministic and consistent with "directory-sorted", and the goal card does not mandate global ordering, so this is a documented behavior note, not a defect.

### N4 — LOW/INFO: legacy `discover_agents_markdown` still does an unbounded `read_text`
The bounded-read fix only touched `_read_layer`; the legacy single-layer public function (`agent_context.py:50-81`) still reads the whole file before truncation. It is no longer used by the product path (`app.py` now imports the layered API) but remains exported/public. Out of scope for this slice; flag for cleanup.

### N5 — LOW/INFO: oversized files are silently dropped, not truncated
Files >128 KiB are refused entirely even though the feature carries a `truncated` flag and per-file char cap. A legitimately large `AGENTS.md` now contributes nothing. This is exactly what the prior review requested ("oversized file refused"), so it is accepted, but the 128 KiB cliff is undocumented in the goal card and untested between 128 KiB and max_chars. Consider documenting the cap.

Other minor/cosmetic: on case-insensitive filesystems (macOS APFS) the reported `path=` uses the queried casing (e.g. `pkg/AGENTS.md` for an on-disk `pkg/agents.md`); harmless and pre-existing, differs from Linux CI.

---

## Test run

```
uv run --extra product-test pytest tests/product/test_agents_markdown_layers.py tests/product/test_chat_agents_markdown.py -q
...................                                                       [100%]
19 passed in 0.62s
```

Counts: **19 passed, 0 failed** = 14 in `test_agents_markdown_layers.py` (9 prior + 5 new: nested-only, root-CLAUDE label, oversized-skip, total-char budget, heavy-dir prune) + 5 in `test_chat_agents_markdown.py`. No new failures; ruff clean; pyright 0.

Coverage gaps remaining: no entry-budget/entry-heavy test (N1); no st_ino==0 fallback test (N2); no between-cap-and-oversize truncation test (N5); F4 TOCTOU has no (and cannot easily have) regression test.

---

## Required changes before promotion

1. **N1 (MEDIUM)**: bound per-directory entries (entry budget and/or bounded fallback), or explicitly document and test the accepted cost. This is the only substantive residual from F2.
2. **F4 (LOW, optional per prior review)**: harden with `O_NOFOLLOW`/fd-based read if convenient; otherwise record accepted risk.
3. **N2/N4/N5 (LOW/INFO)**: address or explicitly record as accepted with dated rationale.

## Independence limitation

Builder and this reviewer share the same underlying model family/provider; this re-review is also by the same model as the prior reviewer and the builder. Independence is limited to role/prompt and the read-only evidence chain, not a genuinely different model. It cannot by itself satisfy RR-0024/RR-0031 independent-review identity for any claim beyond prompt-context, and a provider-independent reviewer is required before promotion beyond S3 prompt-context behavior.
