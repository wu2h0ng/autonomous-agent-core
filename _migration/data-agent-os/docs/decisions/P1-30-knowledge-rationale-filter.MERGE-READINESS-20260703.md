# P1-30 Knowledge Rationale Filter Merge Readiness

Date: 2026-07-03
Branch: `codex/p1-29-knowledge-rationale-review-surface-20260703`
Target: deployment local `main`
Status: ready for founder/CTO-authorized local ff-only merge; not merged; not
pushed; not released

## Scope

This stacked branch contains:

- P1-29: safe internal `review_rationale_codes` on
  `GET /knowledge/assets/quality-summary` items.
- P1-30: safe internal `review_rationale_code` filtering over those codes.

P1-30 adds:

- `GET /knowledge/assets/quality-summary?review_rationale_code=...`
- `KnowledgeAssetQualitySummaryResponse.review_rationale_code_filter`
- OpenAPI enum coverage for the `review_rationale_code` query parameter

This packet records merge readiness only. It is not merge authorization.

## Git Readiness

Commands run from deployment repo before this readiness packet was committed:

```bash
git merge-base --is-ancestor main codex/p1-29-knowledge-rationale-review-surface-20260703
echo ancestor=$?
git rev-list --left-right --count main...codex/p1-29-knowledge-rationale-review-surface-20260703
```

Result:

```text
ancestor=0
0 3
```

Main and feature worktree status both contained only untracked `.agent_runs/`
output. No tracked unstaged or staged changes were present at readiness check.

## Verification Evidence

Stacked branch commits before this readiness packet:

```text
d33b15e feat(knowledge): filter quality queue by rationale
0bfe9a7 docs(knowledge): record rationale review merge readiness
7379c8d feat(knowledge): explain review rationale codes
```

P1-30 RED before implementation:

```text
TypeError: knowledge_asset_quality_summary_service() got an unexpected keyword argument 'review_rationale_code'
KeyError: 'review_rationale_code_filter'
StopIteration
```

Targeted tests after implementation:

```text
Ran 3 tests in 0.243s
OK
```

Related service/API/OpenAPI suite:

```text
Ran 9 tests in 0.402s
OK
```

Branch-local `make ci` after formatting:

```text
Ran 590 tests in 3.309s
OK (skipped=4)
Ran 12 tests in 0.004s
OK
OpenAPI contract is up to date.
=== All CI checks passed ===
```

Branch-local PostgreSQL `ci-local-full`:

```text
Ran 590 tests in 3.609s
OK
Ran 12 tests in 0.003s
OK
OpenAPI contract is up to date.
=== Full local CI parity checks passed ===
```

## Boundary

The stacked branch is internal and read-only for the quality-summary surface. It
does not expose the route to `external_report`, expose KnowledgeAsset
title/content/full related knowledge, expose raw historical trace ids, raw trace
payloads, raw reasons, score breakdowns, correction payloads, metric deltas, or
secret-like fields.

It does not mutate lifecycle/version/retrieval/feedback/adoption state, lower
SQL Safety/EvidenceChain/Approval, promote adoption/value, write feedback,
change connector routing, claim causal attribution/value, claim autonomous-core
or G10 product validation, or allow R4/R5 automatic execution.

## Required Post-Merge Gate

If founder/CTO authorizes the merge:

1. Re-run a fresh `git merge-base --is-ancestor main <branch>` and
   `git rev-list --left-right --count main...<branch>` check because this
   readiness packet adds another docs commit after the `0 3` check above.
2. Run `git merge --ff-only codex/p1-29-knowledge-rationale-review-surface-20260703`
   from deployment local `main`.
3. Run post-merge `make ci`.
4. Run post-merge PostgreSQL `ci-local-full`.
5. Record `P1-30-knowledge-rationale-filter.POST-MERGE-VERIFY-20260703.md`.
6. Update `docs/CURRENT_STATE.yaml` to local-main verified.
