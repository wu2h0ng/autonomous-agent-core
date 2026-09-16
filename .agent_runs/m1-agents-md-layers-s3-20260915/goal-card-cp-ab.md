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

- `tests/product/test_agents_markdown_layers.py` (9): ordering, CLAUDE.md, per-layer
  digest changes on edit, hidden/.git skipped, symlink ignored, layer/char caps, root-only
  render identity, chat prompt includes nested layers, explicit config wins.
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
- The global scan budget can be consumed by instruction-free directories; nested
  discovery then stops (bounded, tested via `max_entries=0`).
- Independent exact-diff review still required before promotion.
