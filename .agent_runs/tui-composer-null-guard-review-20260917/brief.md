# Review Brief — opentui composer overlay-Enter null guard

- Task id: tui-composer-null-guard-review-20260917
- Implementer: opencode (deepseek-flash)  → builder_id
- Reviewer: Claude Code  → reviewed_by  (must differ from builder_id)
- Repo: `autonomous-agent-core/` worktree `.worktrees/tui-composer-textarea`
- Branch: `codex/tui-composer-textarea-20260916`
- Commit under review: `60586374` (parent `18110b89`; merge base `bef15181` = main)
- Status of branch: **WIP / DO NOT MERGE** (PR #63). Runtime view-layer change.
- Scope of this review: the single behavior change in `apps/cli-ts/src/opentui/app.tsx`
  introduced by `60586374`. Reviewers may look at the surrounding branch context
  (the `overlayOwnsEnterRef` / `suppressSyncRef` machinery) because the guard
  interacts with it, but must not request unrelated refactors.
- Why review now: this is the first change on the branch to turn the two red pty
  signals green; it must be independently checked before it is treated as
  verified or documented in CURRENT_STATE.
