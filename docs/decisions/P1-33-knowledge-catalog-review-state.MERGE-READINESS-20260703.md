# P1-33 Knowledge Catalog Review State Merge Readiness

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
- P1-31: safe internal `review_rationale_code_counts` over the currently
  returned quality-summary page.
- P1-32: safe internal review-state fields on
  `GET /knowledge/assets/{asset_id}` detail responses.
- P1-33: safe internal review-state fields on `GET /knowledge/assets` catalog
  items.

P1-33 adds to each catalog item:

- aggregate usage counts from the existing decision-quality surface;
- `quality_status`;
- `review_priority`;
- `recommended_review_action`;
- `review_rationale_codes`.

This packet records merge readiness only. It is not merge authorization.

## Git Readiness

Commands run from both the feature worktree and deployment local `main`
worktree before this readiness packet was committed:

```bash
git merge-base --is-ancestor main codex/p1-29-knowledge-rationale-review-surface-20260703
echo ancestor=$?
git rev-list --left-right --count main...codex/p1-29-knowledge-rationale-review-surface-20260703
git status --short --branch
```

Result:

```text
ancestor=0
0 9
```

Main and feature worktree status both contained only untracked `.agent_runs/`
output. No tracked unstaged or staged changes were present at readiness check.

## Verification Evidence

Stacked branch commits before this readiness packet:

```text
aaf0b85 feat(knowledge): surface catalog review state
01c6bd1 docs(knowledge): record detail review state merge readiness
307657b feat(knowledge): surface detail review state
caa2d6f docs(knowledge): record rationale counts merge readiness
159bf98 feat(knowledge): count rationale review facets
89535cb docs(knowledge): record rationale filter merge readiness
d33b15e feat(knowledge): filter quality queue by rationale
0bfe9a7 docs(knowledge): record rationale review merge readiness
7379c8d feat(knowledge): explain review rationale codes
```

P1-33 RED before implementation:

```text
KeyError: 'proposal_usage_count'
KeyError: 'proposal_usage_count'
AssertionError: required schema fields did not include catalog review-state fields
```

Targeted tests after implementation:

```text
Ran 3 tests in 0.194s
OK
```

Related catalog/detail/decision-quality/quality-summary/OpenAPI suite:

```text
Ran 20 tests in 0.475s
OK
```

Branch-local `make ci` after one mechanical format run:

```text
Ran 592 tests in 3.242s
OK (skipped=4)
Ran 12 tests in 0.004s
OK
OpenAPI contract is up to date.
=== All CI checks passed ===
```

Branch-local PostgreSQL `ci-local-full`:

```text
Ran 592 tests in 3.412s
OK
Ran 12 tests in 0.004s
OK
OpenAPI contract is up to date.
=== Full local CI parity checks passed ===
```

## Boundary

The stacked branch is internal and read-only for the KnowledgeAsset review
surface. It does not expose the routes to `external_report`, expose full
related knowledge externally, expose raw usage trace ids, raw trace events, raw
trace payloads, raw reasons, score breakdowns, correction payloads, metric
deltas, or secret-like fields.

It does not mutate lifecycle/version/retrieval/feedback/adoption state, lower
SQL Safety/EvidenceChain/Approval, promote adoption/value, write feedback,
change connector routing, claim causal attribution/value, claim autonomous-core
or G10 product validation, or allow R4/R5 automatic execution.

## Required Post-Merge Gate

If founder/CTO authorizes the merge:

1. Re-run a fresh `git merge-base --is-ancestor main <branch>` and
   `git rev-list --left-right --count main...<branch>` check because this
   readiness packet adds another docs commit after the `0 9` check above.
2. Run `git merge --ff-only codex/p1-29-knowledge-rationale-review-surface-20260703`
   from deployment local `main`.
3. Run post-merge `make ci`.
4. Run post-merge PostgreSQL `ci-local-full`.
5. Record
   `P1-33-knowledge-catalog-review-state.POST-MERGE-VERIFY-20260703.md`.
6. Update `docs/CURRENT_STATE.yaml` to local-main verified.
