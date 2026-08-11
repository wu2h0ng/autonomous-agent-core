# P1-34 Knowledge Catalog Review Filter Merge Readiness

Date: 2026-07-03
Branch: `codex/p1-34-knowledge-catalog-review-filter-20260703`
Target: deployment local `main`
Status: ready for founder/CTO-authorized local ff-only merge; not merged; not
pushed; not released

## Scope

P1-34 adds safe review-state filters to the internal KnowledgeAsset catalog:

- `review_priority=high|medium|low`
- `review_rationale_code=unused_context_candidate|proposal_context_needs_outcome|outcome_supported_context|adoption_supported_context`

The route echoes the applied filters as:

- `review_priority_filter`
- `review_rationale_code_filter`

This packet records merge readiness only. It is not merge authorization.

## Git Readiness

Commands run before this readiness packet was committed:

```bash
git merge-base --is-ancestor main codex/p1-34-knowledge-catalog-review-filter-20260703
echo ancestor=$?
git rev-list --left-right --count main...codex/p1-34-knowledge-catalog-review-filter-20260703
git status --short --branch
```

Result:

```text
ancestor=0
0 1
```

The feature worktree status contained only untracked `.agent_runs/` output. No
tracked unstaged or staged changes were present at readiness check.

## Verification Evidence

Branch commits before this readiness packet:

```text
be951d7 feat(knowledge): filter catalog by review state
```

P1-34 RED before implementation:

```text
TypeError: knowledge_asset_catalog_service() got an unexpected keyword argument 'review_priority'
KeyError: 'review_priority_filter'
StopIteration
```

Targeted tests after implementation:

```text
Ran 3 tests in 0.252s
OK
```

Related catalog/detail/quality/OpenAPI suite:

```text
Ran 19 tests in 0.944s
OK
```

Branch-local `make ci` after one mechanical format run:

```text
Ran 594 tests in 7.490s
OK (skipped=4)
Ran 12 tests in 0.008s
OK
OpenAPI contract is up to date.
=== All CI checks passed ===
```

Branch-local PostgreSQL `ci-local-full`:

```text
Ran 594 tests in 6.140s
OK
Ran 12 tests in 0.007s
OK
OpenAPI contract is up to date.
=== Full local CI parity checks passed ===
```

## Boundary

The branch is internal and read-only for the KnowledgeAsset catalog review
surface. It does not expose the route to `external_report`, expose full related
knowledge externally, expose raw usage trace ids, raw trace events, raw trace
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
   readiness packet adds another docs commit after the `0 1` check above.
2. Run `git merge --ff-only codex/p1-34-knowledge-catalog-review-filter-20260703`
   from deployment local `main`.
3. Run post-merge `make ci`.
4. Run post-merge PostgreSQL `ci-local-full`.
5. Record
   `P1-34-knowledge-catalog-review-filter.POST-MERGE-VERIFY-20260703.md`.
6. Update `docs/CURRENT_STATE.yaml` to local-main verified.
