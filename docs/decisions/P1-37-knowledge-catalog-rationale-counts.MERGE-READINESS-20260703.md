# P1-37 Knowledge Catalog Rationale Counts Merge Readiness

Date: 2026-07-03
Branch: `codex/p1-37-knowledge-catalog-rationale-counts-20260703`
Implementation commit: `57a7fd4`
Target branch: local `main`
Status: merge-readiness prepared; not merged, pushed, or released

## Scope

P1-37 adds safe `review_rationale_code_counts` to the internal read-only
`GET /knowledge/assets` catalog. Counts summarize the currently returned
catalog result by allowlisted review rationale code.

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
## codex/p1-37-knowledge-catalog-rationale-counts-20260703
?? .agent_runs/
```

Only untracked `.agent_runs/` was present outside git-tracked task files.

## Verification Evidence

Recorded in
`docs/decisions/P1-37-knowledge-catalog-rationale-counts.IMPLEMENTATION-20260703.md`:

- RED observed before implementation:
  `KeyError: 'review_rationale_code_counts'` and missing OpenAPI required field
  assertion
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
- tracked worktree changes appear outside the P1-37 readiness packet
- CI or OpenAPI checks regress
- the slice starts exposing raw KnowledgeAsset internals or mutating
  lifecycle/retrieval/feedback/adoption state
- a merge would imply push, release, external product claim, autonomous-core/G10
  validation claim, or R4/R5 automatic execution

## Boundary

This packet is not merge authorization by itself. It records that the branch is
locally fast-forwardable and verified for a cautious local merge if authorized.
