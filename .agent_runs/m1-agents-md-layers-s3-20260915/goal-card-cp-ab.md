# Goal Card + CP/AB — S3 LAYERED PROJECT INSTRUCTIONS

> Status: `IMPLEMENTED / PENDING_INDEPENDENT_EXACT_DIFF_REVIEW`
> Track: Product Track, low/medium risk (prompt-context only; no authority change).
> Cast: P2-7 M1 route A, target Python core. Base `origin/main` @ `18d7b9b0`.
> Claim ceiling: no parity / autonomy / release claim.

## 1. Goal

GAP-ANALYSIS M1 item: *"AGENTS.md/CLAUDE.md 分层加载 … 无（隐含）单层加载已有"*. Before
this slice only the workspace-root `AGENTS.md` was loaded. After it, project instruction
files load as ordered layers (root first, then nested), each carrying its own `sha256`
change digest.

## 2. What was implemented

- `agent_context.py`: `discover_agents_markdown_layers(workspace, *, max_layers=8,
  max_chars_per_file=12000, max_total_chars=24000)` — deterministic, bounded; root first,
  then directory-sorted nested `AGENTS.md`/`CLAUDE.md`; `.git`/hidden dirs skipped;
  fail-closed per layer (symlink/out-of-workspace/unreadable/non-UTF-8 skipped).
- `layered_agents_markdown_system_section(layers)` — root layer renders EXACTLY like the
  legacy `agents_markdown_system_section` (no drift for the root-only case); nested layers
  render with `path=` + `sha256=`.
- `apps/api_server/app.py` `_loop_config_with_agents` now uses the layered discovery.

## 3. Boundaries

- Prompt context only. No authority, permission, capability or C7 change. An explicit
  `loop_config` still wins over discovered layers.
- The root-only case is byte-identical to the previous behaviour (asserted by test), so no
  regression for the common case.

## 4. Verification

- `tests/product/test_agents_markdown_layers.py` (17): ordering, CLAUDE.md, per-layer
  digest changes on edit, hidden/.git/pruned-dir skips, symlink ignored, layer/char/dir
  caps, nested-only provenance, root CLAUDE.md label, oversized-file skip, huge-dir
  smoke, root-only render identity, chat prompt includes nested layers, explicit config
  wins.
- Existing `test_chat_agents_markdown.py` (5) still passes.
- Full `tests/product` 23 failed == base, zero new. Ruff clean; pyright 0.

## 5. Bounds (explicit)

- Per file: **128 KiB hard cap** (`_MAX_BYTES_PER_FILE`). A layered file over the cap is
  **skipped** (fail closed); the legacy `discover_agents_markdown` **truncates** to the
  cap to preserve its pre-existing truncate contract.
- Per loose-cased directory probe: 500 entries (`_MAX_ENTRIES_PER_DIR`); global scan
  budget 20 000 entries + 2 000 directories; 8 layers; 24 000 total chars.

## 6. Residual / honesty

- "On-demand" (path-targeted) layering is NOT implemented; this is a bounded whole-tree
  scan. A target-path variant can be added later if a real caller needs it.
- The directory budget is tested (`max_dirs=0` -> root only). The entry budget
  (`max_entries`) bounds only the loose-cased fallback scan; an exact-case `AGENTS.md`
  is always found by the cheap O(1) probe, so the budget is not exercised on
  case-insensitive filesystems (macOS) — documented, not asserted.
- Per-dir cap (500): a loose-cased instruction file past entry 500 in a directory is
  not found (intended bound; untested on case-insensitive macOS).
- "Root-only byte-identical to legacy" holds only for root files ≤128 KiB. A root file
  **>128 KiB** is SKIPPED by the layered path (fail closed) whereas the legacy function
  truncates it to 12000 chars — an intentional bounded-read divergence.
- Legacy `discover_agents_markdown` on an oversize (>128 KiB) file now (a) truncates at
  the cap with `errors="ignore"` and (b) digests only the read prefix, so two files
  differing only past the cap share a digest. Bounded-read consequences; the layered
  path refuses oversize instead (fail closed).
- All S3 reviews are same-model; a provider-independent reviewer is required before
  promotion.
