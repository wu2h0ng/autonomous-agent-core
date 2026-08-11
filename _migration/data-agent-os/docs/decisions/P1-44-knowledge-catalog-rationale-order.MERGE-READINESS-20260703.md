# P1-44 Knowledge Catalog Rationale Order Merge Readiness

Date: 2026-07-03
Branch: `codex/p1-44-knowledge-catalog-rationale-order-20260703`
Target branch: local `main`
Status: ready for local fast-forward merge if conditions still hold immediately before merge; not pushed or released

## Scope

P1-44 adds catalog-only `order_by=review_rationale_code` to internal read-only
`GET /knowledge/assets`. The ordering is applied after filters and before
pagination, using:

```text
unused_context_candidate -> proposal_context_needs_outcome -> outcome_supported_context -> adoption_supported_context
```

`GET /knowledge/assets/quality-summary` remains limited to
`order_by=review_priority`.

## Pre-Merge Checks

```text
git merge-base --is-ancestor main HEAD
ancestor=0

git rev-list --left-right --count main...HEAD
0 1

git status --short --branch
## codex/p1-44-knowledge-catalog-rationale-order-20260703
?? .agent_runs/
```

Only untracked `.agent_runs/` is present and remains excluded from the merge.

## Verification Evidence

Branch-local verification recorded in
`docs/decisions/P1-44-knowledge-catalog-rationale-order.IMPLEMENTATION-20260703.md`:

- targeted RED/GREEN: 3 tests OK after implementation;
- related KnowledgeAsset/API/OpenAPI subset: 26 tests OK;
- `make ci`: 598 primary unittest tests OK / 4 skipped plus 12 eval OK;
- PostgreSQL `ci-local-full`: 598 primary unittest tests OK plus 12 eval OK;
- threshold report passed;
- OpenAPI contract up to date.

## Stop Conditions

Stop instead of merging if:

- local `main` is no longer an ancestor of this branch;
- tracked unrelated changes appear;
- verification regresses;
- merge would imply push, release, external product claim, autonomous-core/G10
  product validation, or any R4/R5 execution claim.

## Boundary

This readiness packet does not authorize push or release. P1-44 remains an
internal-only read surface; it does not mutate KnowledgeAsset lifecycle,
versioning, retrieval, feedback, adoption, trace, connector routing, SQL
Safety, EvidenceChain, Approval, or R4/R5 behavior. It does not expose raw
usage trace ids, raw trace events, raw trace payloads, raw reasons, score
breakdowns, correction payloads, metric deltas, or secret-like fields.
