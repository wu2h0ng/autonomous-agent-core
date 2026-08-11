# P1-31 Knowledge Rationale Counts Implementation

Date: 2026-07-03
Branch: `codex/p1-29-knowledge-rationale-review-surface-20260703`
Layer: deployment
Status: branch-local verified; not merged; not pushed; not released

## Scope

Add safe internal facet counts for P1-29/P1-30 rationale review codes on
`GET /knowledge/assets/quality-summary`.

P1-31 adds:

- `KnowledgeAssetQualitySummaryResponse.review_rationale_code_counts`
- OpenAPI schema coverage for the count map
- service/API tests proving the map is page-scoped like the existing
  `quality_status_counts`, `review_priority_counts`, and
  `recommended_review_action_counts`

Allowed count keys:

- `unused_context_candidate`
- `proposal_context_needs_outcome`
- `outcome_supported_context`
- `adoption_supported_context`

## Product Behavior

Internal reviewers can now see how the currently returned quality-summary page
breaks down by safe rationale code. This supports queue triage after filtering
or pagination without exposing raw trace payloads, KnowledgeAsset content, raw
reasons, score breakdowns, or correction payloads.

The counts are derived from the already allowlisted `review_rationale_codes`
present on each returned item.

## Safety Boundaries

This slice is internal and read-only. It does not:

- expose the quality-summary route to `external_report`;
- expose KnowledgeAsset title/content/full related_knowledge;
- expose raw historical trace ids or raw trace payloads;
- expose raw reasons, raw score breakdowns, correction payloads, or metric deltas;
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
KeyError: 'review_rationale_code_counts'
KeyError: 'review_rationale_code_counts'
AssertionError: required schema fields did not include review_rationale_code_counts
```

Targeted tests passed after implementation:

```text
Ran 3 tests in 0.215s
OK
```

Related service/API/OpenAPI suite passed:

```text
Ran 9 tests in 0.356s
OK
```

Branch-local CI passed after one mechanical format run:

```text
make ci PYTHON=.venv/bin/python3
Ran 590 tests in 3.288s
OK (skipped=4)
Ran 12 eval tests in 0.003s
OK
OpenAPI contract is up to date.
=== All CI checks passed ===
```

PostgreSQL local parity passed:

```text
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full PYTHON=.venv/bin/python3

Ran 590 tests in 3.492s
OK
Ran 12 eval tests in 0.004s
OK
OpenAPI contract is up to date.
=== Full local CI parity checks passed ===
```

## Interpretation

This is a deployment-layer reviewer ergonomics slice. It makes the existing
safe rationale surface easier to scan and filter without expanding external
reporting, lifecycle mutation, value promotion, or execution authority.
