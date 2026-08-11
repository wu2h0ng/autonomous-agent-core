# P1-60 Correction Knowledge Rationale Merge Readiness Refresh

Date: 2026-07-03
Branch: `codex/p1-60-correction-knowledge-rationale-20260703`
Implementation commits: `0dfa1d9`, `8c6a925`
Status: merge-ready refresh after recall-metadata boundary hardening; not
merged, pushed, or released.

## Why This Refresh Exists

The first readiness packet was recorded after the initial implementation commit.
Before merge, a stricter boundary regression was added:

- `tests.unit.test_outcome_service.RecordOutcomeServiceTest.test_correction_responses_skip_rationale_without_recall_metadata`

That test requires `knowledge_context_refs` to keep all source-trace proposal
refs while `knowledge_context_rationale` only projects refs that also have
persisted recall-score metadata. Commit `8c6a925` implements that boundary.

## Linearity

Commands:

```bash
git merge-base --is-ancestor main HEAD; printf 'ancestor=%s\n' $?
git rev-list --left-right --count main...HEAD
```

Result:

- `git merge-base --is-ancestor main HEAD` returned `0`.
- `main...HEAD` was `0 3` before this docs refresh commit.

Run a final fresh status and linearity check immediately before local
`ff-only` merge.

## Verification Evidence

Branch-local verification after the hardening commit:

- Focused correction rationale and OpenAPI tests: 5 tests OK.
- Related correction/runtime/API/OpenAPI regression: 11 tests OK.
- `make ci`: Ruff check passed; format check passed; 609 primary unittest tests
  OK / 4 skipped; 12 eval tests OK; threshold report passed; OpenAPI contract
  up to date.
- PostgreSQL `ci-local-full`: 609 primary unittest tests OK; 12 eval tests OK;
  threshold report passed; OpenAPI contract up to date; full local CI parity
  checks passed.

## Merge Conditions

Allowed merge type: local `git merge --ff-only` to deployment `main`.

Stop conditions:

- `main` is no longer an ancestor.
- Tracked working tree changes appear before merge, except this scoped readiness
  refresh before it is committed.
- Post-merge `make ci` or PostgreSQL `ci-local-full` fails.

## Boundaries

- Local merge only.
- No push.
- No release.
- No external product claim.
- No KnowledgeAsset content/title, raw trace payload, raw run parameters, tool
  output, related knowledge body, metric delta, score-breakdown internals, or
  secret-like fields are exposed.
- `knowledge_context_rationale` is not fabricated for proposal refs that lack
  persisted recall-score metadata.
- Self-report `/outcomes` still does not promote knowledge.
- `/adoptions` remains the only realized external-value promotion path.
- No autonomous-core, G10, AGI, autonomy, R4/R5, or business-action execution
  claim.
