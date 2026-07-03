# P1-61 Knowledge Usage Rationale Events Merge Readiness

Date: 2026-07-03
Branch: `codex/p1-61-knowledge-usage-rationale-events-20260703`
Status: merge-ready for local ff-only merge after the implementation commit;
not merged, pushed, or released.

## Verification Evidence

Branch-local verification passed before this readiness packet:

- Focused usage-events rationale/OpenAPI tests: 4 tests OK.
- Related usage-events/decision-quality/quality-summary/API/OpenAPI regression:
  14 tests OK.
- `make ci`: Ruff check passed; format check passed; 609 primary unittest tests
  OK / 4 skipped; 12 eval tests OK; threshold report passed; OpenAPI contract
  up to date.
- PostgreSQL `ci-local-full`: 609 primary unittest tests OK; 12 eval tests OK;
  threshold report passed; OpenAPI contract up to date; full local CI parity
  checks passed.

## Merge Conditions

Allowed merge type: local `git merge --ff-only` to deployment `main`.

Before merge, rerun:

```bash
git status --short --branch
git merge-base --is-ancestor main HEAD; printf 'ancestor=%s\n' $?
git rev-list --left-right --count main...HEAD
```

Stop conditions:

- `main` is no longer an ancestor.
- Tracked working tree changes appear before merge.
- Post-merge `make ci` or PostgreSQL `ci-local-full` fails.

## Boundaries

- Local merge only.
- No push.
- No release.
- No external product claim.
- Internal usage-events projection only; catalog/latest-summary remains
  unchanged.
- No KnowledgeAsset content/title, raw trace payload, raw run parameters, tool
  output, related knowledge body, metric delta, score-breakdown internals, or
  secret-like fields are exposed.
- No lifecycle/review/retrieval/feedback/adoption mutation.
- No autonomous-core, G10, AGI, autonomy, R4/R5, or business-action execution
  claim.
