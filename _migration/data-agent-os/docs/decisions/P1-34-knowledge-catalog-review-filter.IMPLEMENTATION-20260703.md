# P1-34 Knowledge Catalog Review Filter Implementation

Date: 2026-07-03
Branch: `codex/p1-34-knowledge-catalog-review-filter-20260703`
Layer: deployment
Status: branch-local verified; not merged; not pushed; not released

## Scope

Add safe review-state filters to the internal KnowledgeAsset catalog route:

- `GET /knowledge/assets?review_priority=high|medium|low`
- `GET /knowledge/assets?review_rationale_code=<allowlisted-code>`

The route now echoes:

- `review_priority_filter`
- `review_rationale_code_filter`

The implementation reuses the existing allowlisted review-priority and
review-rationale normalization used by the quality-summary surface. The
filters apply after the lifecycle filter and before the response is returned.

## Product Behavior

Internal reviewers can now use the main asset catalog as an actionable review
queue instead of switching to the quality-summary route first. This keeps the
P1-33 catalog review-state fields useful for operational triage while
preserving the internal-only and read-only boundary.

## Safety Boundaries

This slice does not:

- expose the catalog route to `external_report`;
- expose raw usage trace ids, raw trace events, raw trace payloads, raw reasons,
  score breakdowns, correction payloads, metric deltas, or secret-like fields;
- change lifecycle/version/retrieval/feedback/adoption state;
- change review actions, publish/deprecate behavior, or promotion semantics;
- lower SQL Safety/EvidenceChain/Approval gates;
- change connector routing or action execution;
- claim causal attribution/value;
- claim autonomous-core/G10 product validation;
- enable R4/R5 automatic execution.

## TDD Evidence

RED was observed before implementation:

```text
TypeError: knowledge_asset_catalog_service() got an unexpected keyword argument 'review_priority'
KeyError: 'review_priority_filter'
StopIteration
```

Targeted tests passed after implementation:

```text
Ran 3 tests in 0.252s
OK
```

Related catalog/detail/quality/OpenAPI suite passed:

```text
Ran 19 tests in 0.944s
OK
```

Branch-local `make ci` passed after one mechanical format run:

```text
Ran 594 tests in 7.490s
OK (skipped=4)
Ran 12 tests in 0.008s
OK
OpenAPI contract is up to date.
=== All CI checks passed ===
```

Branch-local PostgreSQL local parity passed:

```text
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full PYTHON=.venv/bin/python3

Ran 594 tests in 6.140s
OK
Ran 12 tests in 0.007s
OK
OpenAPI contract is up to date.
=== Full local CI parity checks passed ===
```

## Interpretation

This is a deployment-layer review ergonomics slice. It makes the catalog more
usable as a governed internal review queue while preserving the aggregate-only,
read-only, internal-only KnowledgeAsset boundary.
