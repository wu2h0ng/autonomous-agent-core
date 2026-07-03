# P1-47 Knowledge Detail Lifecycle Count Merge Readiness

Date: 2026-07-03
Branch: `codex/p1-47-knowledge-detail-lifecycle-count-20260703`
Implementation head: `b0ffbba`
Base checked: local `main@ee38bda`
Status: ready for cautious local ff-only merge; not pushed or released

## Scope

P1-47 adds `lifecycle_event_count` to the internal, read-only
`GET /knowledge/assets/{asset_id}` detail surface. The count covers only safe
KnowledgeAsset lifecycle trace steps for the requested asset:

- `knowledge_review_decision`;
- `knowledge_publish_decision`;
- `knowledge_deprecate_decision`.

It does not return lifecycle event bodies or raw lifecycle reasons.

## Readiness Checks

```text
git merge-base --is-ancestor main HEAD
```

Result: exit code 0.

```text
git rev-list --left-right --count main...HEAD
```

Result: `0 1`.

```text
git status --short --branch
```

Result: current branch is
`codex/p1-47-knowledge-detail-lifecycle-count-20260703`; only `.agent_runs/`
remains untracked.

## Verification Already Passed

- Targeted RED/GREEN: 3 tests OK.
- Related KnowledgeAsset/API/OpenAPI subset: 23 tests OK.
- `make ci`: 599 primary unittest tests OK / 4 skipped, 12 eval tests OK,
  threshold report passed, OpenAPI up to date.
- PostgreSQL `ci-local-full`: 599 primary unittest tests OK / 4 skipped,
  12 eval tests OK, threshold report passed, OpenAPI up to date, full local
  parity checks passed.

## Boundary

This merge would remain local-only unless separately pushed. It does not:

- expose raw lifecycle events, raw lifecycle reasons, raw trace payloads,
  related knowledge content, raw score breakdowns, correction payloads,
  metric_deltas, or secret-like fields;
- mutate lifecycle, version, retrieval, feedback, adoption, connector routing,
  or approval state through the read endpoint;
- lower SQL Safety, EvidenceChain, Approval, Trace, or API scope gates;
- claim autonomous-core/G10 validation, causal/value attribution, AGI, or R4/R5
  execution capability.
