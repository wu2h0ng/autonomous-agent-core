# Verification — 60586374

Environment: worktree `.worktrees/tui-composer-textarea`; `apps/cli-ts/node_modules`
supplied by symlink to a sibling worktree holding `@opentui/core@0.5.11` (the
symlink is untracked and was removed afterwards). `uv` created the worktree
`.venv`. `git diff --check` clean. Branch clean, in sync with origin.

## Unit / static

```
$ npm test          → # tests 158  # pass 158  # fail 0
                    → # tests  19  # pass  19  # fail 0
$ npm run typecheck → exit 0
$ npm run build     → exit 0
```

Note: on the first `npm test` run the second batch (app/homeview) reported
18/19 with one timing-sensitive failure; an immediate re-run of
`test/app.test.tsx test/homeview.test.tsx` was 19/19. The failure was not
reproduced. Reviewer should judge whether that flake is acceptable.

## pty evidence (hermetic dev daemon, no provider key, no network)

```
$ uv run python scripts/pty_fullscreen_parity_b.py
HISTORY_PREVIOUS: True
MENTION_TAB_COMPLETED: True
MARKDOWN_RENDER_PATH_OK (smoke, not a formatting test): True
SLICE_B_ALL_SIGNALS_VERIFIED: True

$ uv run python scripts/pty_fullscreen_parity_a.py
PALETTE_ENTER_RAN_STATUS: True
SELECTOR_SHOWN: True

$ uv run python scripts/pty_fullscreen_parity_c.py
EDITOR_ROUNDTRIP: True

$ uv run python scripts/pty_fullscreen_composer_invariant.py
PALETTE_ENTER_RAN_STATUS: True
PROCESS_ALIVE_AFTER_ENTER: True
COMMAND_RAN_EXACTLY_ONCE: True
INVARIANT_OK: True

$ uv run python scripts/pty_fullscreen_p3a.py
RESUMED: True
TYPABLE_WITH_AGENTS_PANEL: True
```

## Trace confirmation (instrumented run, instrumentation removed before commit)

After the fix:
```
ONSUBMIT {"agentsPanel":false,"overlayOwnsEnter":false,"plain":"hi"}
SUBMIT   {"value":"hi","text":"hi"}
HISTORY  {"action":"prev","mirrorInput":"","recalled":"hi","size":1}
KEY      {"name":"tab","layer":"mention","action":"complete"}
SUBMIT   {"value":"@zzmentionfile ","text":"@zzmentionfile"}
```

## Git state

- `60586374` committed and pushed to `origin/codex/tui-composer-textarea-20260916`.
- `main` (`bef15181`) untouched; no merge performed.
- PR #63 kept OPEN / DO NOT MERGE; an update comment with the root cause was posted.
