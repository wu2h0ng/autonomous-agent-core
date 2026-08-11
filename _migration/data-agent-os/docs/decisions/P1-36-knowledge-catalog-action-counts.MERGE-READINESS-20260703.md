# P1-36 Knowledge Catalog Action Counts Merge Readiness

Date: 2026-07-03
Branch: `codex/p1-36-knowledge-catalog-action-counts-20260703`
Implementation commit: `1dd546f`
Target branch: local `main`
Status: merge-readiness prepared; not merged, pushed, or released

## Scope

P1-36 adds safe `recommended_review_action_counts` to the internal read-only
`GET /knowledge/assets` catalog. Counts summarize the currently returned
catalog result by allowlisted recommended review action.

## Merge Readiness Checks

Fast-forward ancestry:

```text
git merge-base --is-ancestor main HEAD
ancestor=0
```

Branch divergence:

```text
git rev-list --left-right --count main...HEAD
0 1
```

Worktree state before this readiness packet:

```text
## codex/p1-36-knowledge-catalog-action-counts-20260703
?? .agent_runs/
```

Only untracked `.agent_runs/` was present outside git-tracked task files.

## Verification Evidence

Recorded in
`docs/decisions/P1-36-knowledge-catalog-action-counts.IMPLEMENTATION-20260703.md`:

- RED observed before implementation:
  `KeyError: 'recommended_review_action_counts'` and missing OpenAPI required
  field assertion
- Targeted tests: 3 OK
- Related KnowledgeAsset/API/OpenAPI tests: 22 OK
- `make ci`: 594 primary unittest tests OK / 4 skipped, 12 eval tests OK,
  threshold report passed, OpenAPI contract up to date
- PostgreSQL `ci-local-full`: 594 primary unittest tests OK, 12 eval tests OK,
  threshold report passed, OpenAPI contract up to date, full parity checks
  passed

## Stop Conditions

Do not merge if any of the following appear before merge:

- `main` is no longer an ancestor of this branch
- tracked worktree changes appear outside the P1-36 readiness packet
- CI or OpenAPI checks regress
- the slice starts exposing raw KnowledgeAsset internals or mutating
  lifecycle/retrieval/feedback/adoption state
- a merge would imply push, release, external product claim, autonomous-core/G10
  validation claim, or R4/R5 automatic execution

## Boundary

This packet is not merge authorization by itself. It records that the branch is
locally fast-forwardable and verified for a cautious local merge if authorized.
*** End Patch
