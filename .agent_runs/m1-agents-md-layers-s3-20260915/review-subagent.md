# Independent Exact-Diff Review — S3 Layered AGENTS.md/CLAUDE.md

- Reviewer: independent subagent, adversarial exact-diff review (read-only on source/tests)
- Worktree: `autonomous-agent-core/.worktrees/m1-danger-cmd-20260915`
- Commit under review: `21c20246` (parent `ad9d9f67`; base `origin/main` `18d7b9b0`)
- Gate doc: `.agent_runs/m1-agents-md-layers-s3-20260915/goal-card-cp-ab.md`
- Files inspected: `packages/os_core/src/agent_os_core/agent_context.py`, `apps/api_server/app.py` (`_loop_config_with_agents`, imports), `packages/os_core/src/agent_os_core/__init__.py`, `tests/product/test_agents_markdown_layers.py`, `tests/product/test_chat_agents_markdown.py`

## Verdict

**APPROVE_WITH_CHANGES**

The fail-closed per-layer invariants, determinism, ordering and the root-only render identity all hold. Bounds (`max_layers`, `max_chars_per_file`, `max_total_chars`) are enforced on the *returned* layers. However the new layered feature has one correctness defect (first layer mislabeled as root) and two resource-bound defects (unbounded tree scan; unbounded bytes read per file). These should be fixed before promotion.

---

## Findings

### F1 — MEDIUM (correctness): first layer is mislabeled as the root when no readable root file exists

`layered_agents_markdown_system_section` unconditionally treats `layers[0]` as the root and renders it with the legacy header (`agent_context.py:159-172`). But `discover_agents_markdown_layers` only prepends the root file when one exists and reads successfully (`agent_context.py:124-126`). When the root file is absent (or fails closed: symlink, non-UTF-8, unreadable), `layers[0]` is a **nested** file and is rendered as:

```
# Project AGENTS.md (sha256=<nested>)
<nested content>
```

i.e. the nested file is presented to the model as the workspace-root AGENTS.md and its `path=` attribution is dropped. Concrete trees (all produce this):

- workspace with no root file, only `pkg/AGENTS.md` → rendered as `Project AGENTS.md`, `path=` lost.
- root `AGENTS.md` is non-UTF-8/unreadable/symlink, `pkg/AGENTS.md` present → same.
- root has only `CLAUDE.md` (now discovered) → rendered as `Project AGENTS.md` (misnames the file).

This contradicts the goal card's per-layer `path=` contract and the "root layer renders EXACTLY like legacy" statement (which is only true when a readable root file exists). It is a provenance/attribution defect in the primary new capability, not an authority change.

Required change: carry an explicit root marker (e.g. `is_root` on `AgentsMarkdownContext`, or compare the layer path against the root filename) and only use the legacy header for the true root; render all nested/failed-root layers with the `# Nested AGENTS.md (path=..., sha256=...)` header. Add a nested-only regression test.

### F2 — MEDIUM (unbounded work): caps do not bound discovery; full-tree `rglob` runs on every session open

`ordered` is built by scanning the **entire** workspace (`agent_context.py:123-132`) and `max_layers`/`max_total_chars` are applied only afterwards (`:134-150`). `_pick` additionally calls `sorted(directory.iterdir())` for every non-hidden directory (`:118-120`), and `rglob("*")` traverses into skipped dirs (e.g. `.git`, `node_modules`) before the `_is_hidden_dir` filter drops them. Cost is therefore independent of the caps: a 10k-file tree took ~0.15s and was unchanged for `max_layers` 1 / 8 / 100. `_loop_config_with_agents` (`app.py:214`) calls this synchronously on every chat-session open, and `workspace` is caller-supplied → latency/DoS on a large or crafted tree.

Required change: prune hidden dirs during traversal (e.g. `os.walk(..., followlinks=False)` with in-place `dirnames` filtering) and introduce an explicit directory/entry scan budget (or a size/entry guard that short-circuits once `max_layers` candidates are known). Add a guard test.

### F3 — MEDIUM (unbounded read): `max_chars_per_file`/`max_total_chars` do not bound bytes read

`_read_layer` calls `path.read_text(encoding="utf-8")` and truncates *after* the full file is decoded (`agent_context.py:79-89`). A multi-GB `AGENTS.md` is fully allocated/decoded before `raw[:max_chars]`; up to `max_layers` such files are read. The char caps bound only the returned string, not memory/IO. The legacy single-file path had the same read pattern, but the layered version multiplies the number of such reads. (Verified: 5 MB file → content 12 000 chars, but entire 5 MB was read into memory.)

Required change: use a bounded read (`open(...).read(max_chars + 1)`) or a pre-read `stat().st_size` guard; preserve the digest contract (full-file sha256) explicitly or document the change. Add a huge-file test.

### F4 — LOW: TOCTOU on the symlink check

`is_symlink()` is checked separately from `read_text()` without `O_NOFOLLOW`/fd-based read (`agent_context.py:72-82`); a concurrent swap could read an out-of-workspace target. Defense-in-depth only.

### F5 — LOW: hardlinks are not deduped

Dedup keys on `path.resolve()` (`:138`), which conflates symlinks but not hardlinks. The same inode can be injected up to `max_layers` times (bounded by the char caps). Cosmetic amplification.

### F6 — LOW: docstring drift

`_loop_config_with_agents` still documents `discover_agents_markdown` / its `None` return (`app.py:210-213`) while now calling the layered API; update to describe `layers` + per-layer fail-closed semantics.

### F7 — LOW: root `CLAUDE.md` is rendered under the `# Project AGENTS.md` header (ties to F1); the header should name the actual file.

---

## Verified invariants (non-findings)

Adversarial probes confirmed the following behave correctly:

- **Fail-closed per layer**: a symlinked file (root or nested, including a nested symlink whose target *is* an in-workspace file) is skipped; a symlinked directory pointing outside is not traversed (rglob no-follow) and yields nothing; root symlink to outside → `()`.
- **Out-of-workspace via `..`**: `resolve()` + `relative_to(root)` rejects; nested-only/`..` cannot escape.
- **Unreadable** (`chmod 000`) → `()`; **non-UTF-8** → `()`; special/FIFO files excluded by `is_file()`.
- **Hidden/`.git` bypass**: `.git`, `.hidden`, and deep `a/.git` are skipped; a legitimate `a/b/AGENTS.md` is kept.
- **Case-insensitive dupes**: handled (exact name first, then sorted case-insensitive fallback); no duplicate injection on case-insensitive FS.
- **Determinism**: `sorted(rglob(...))` for dirs and `sorted(iterdir())` in `_pick` give a stable lexicographic order across runs (verified identical across repeated calls).
- **Caps enforced on output**: `max_layers` never exceeded; `max_chars_per_file` enforced; `max_total_chars` enforced exactly (verified sum 15000 with cap 15000, second layer marked `truncated`).
- **Root-only render identity**: with only `AGENTS.md`, `layered_agents_markdown_system_section(discovered) == agents_markdown_system_section(discovered[0])` byte-for-byte; digest/path/content identical to the legacy single-layer path.
- **Explicit `loop_config` still wins** (`app.py:214-221`), so an explicit system prompt is not overridden.

---

## Proposed break trees (concrete)

1. Nested-only: `pkg/AGENTS.md="nested rules"`, no root → rendered as `Project AGENTS.md` with no `path=` (F1).
2. Root fail-closed + nested: root `AGENTS.md` with invalid UTF-8 bytes + `pkg/AGENTS.md` valid → nested mislabeled as root (F1).
3. Large tree: `node_modules`/`.git` with 10⁵–10⁶ files, or a directory fan-out of 10⁵ dirs → full-tree scan per session open (F2).
4. Huge file: single `AGENTS.md` of several GB → full decode before truncation (F3).
5. Hardlink fan-out: same inode hardlinked as `*/AGENTS.md` across many dirs → repeated injection up to `max_layers` (F5).

---

## Test run

```
uv run --extra product-test pytest tests/product/test_agents_markdown_layers.py tests/product/test_chat_agents_markdown.py -q
..............                                                           [100%]
14 passed in 0.59s
```

Counts: **14 passed, 0 failed** = 9 new (`test_agents_markdown_layers.py`) + 5 existing (`test_chat_agents_markdown.py`). No new failures vs base.

Test-coverage gaps that let F1/F2/F3 through: no nested-only/failed-root labeling test; no `max_chars_per_file`/`max_total_chars` assertion; no huge-file or large-tree/scan-bound test; no explicit determinism test; no nested non-UTF-8/unreadable test.

---

## Required changes before promotion

1. **F1**: explicit root marker; nested-only and failed-root layers must render with `path=`/nested header. Add nested-only test.
2. **F2**: prune hidden dirs during traversal and add an explicit scan budget / short-circuit. Add guard test.
3. **F3**: bounded read or size guard, preserving or explicitly redefining the digest contract. Add huge-file test.
4. **F4/F5/F6/F7**: TOCTOU hardening, hardlink dedup or documented acceptance, docstring update, correct root filename in header (optional/low).

## Independence limitation

The builder and this reviewer share the same underlying model family/provider (same model as builder); independence is limited to the role/prompt and the read-only evidence chain, not to a genuinely different model. This review therefore cannot by itself satisfy RR-0024/RR-0031 independent-review identity requirements for a stronger claim; a provider-independent reviewer is required before any promotion beyond prompt-context.
