# P1-33 Knowledge Catalog Review State Implementation

Date: 2026-07-03
Branch: `codex/p1-29-knowledge-rationale-review-surface-20260703`
Layer: deployment
Status: branch-local verified; not merged; not pushed; not released

## Scope

Make the internal KnowledgeAsset catalog list consistent with the P1-32 detail
surface by adding the same safe review-state fields to each
`GET /knowledge/assets` catalog item.

P1-33 adds to each catalog item:

- `proposal_usage_count`
- `correction_usage_count`
- `outcome_correction_count`
- `adoption_correction_count`
- `distinct_usage_trace_count`
- `quality_status`
- `review_priority`
- `recommended_review_action`
- `review_rationale_codes`

The fields are derived from the existing decision-quality aggregate and the
same allowlisted status mappings used by quality summary and asset detail.

## Product Behavior

Internal reviewers can triage the catalog list without opening each asset
detail first. The default catalog still lists active/published assets, supports
the existing lifecycle filter, and remains read-only.

The route does not return `usage_trace_ids`; it keeps only safe aggregate
counts and allowlisted review rationale codes.

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
KeyError: 'proposal_usage_count'
KeyError: 'proposal_usage_count'
AssertionError: required schema fields did not include catalog review-state fields
```

Targeted tests passed after implementation:

```text
Ran 3 tests in 0.487s
OK
```

Related catalog/detail/quality/OpenAPI suite passed:

```text
Ran 20 tests in 0.940s
OK
```

Branch-local CI passed after one mechanical format run:

```text
make ci PYTHON=.venv/bin/python3
Ran 592 tests in 5.898s
OK (skipped=4)
Ran 12 eval tests in 0.004s
OK
OpenAPI contract is up to date.
=== All CI checks passed ===
```

PostgreSQL local parity passed:

```text
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full PYTHON=.venv/bin/python3

Ran 592 tests in 6.008s
OK
Ran 12 eval tests in 0.004s
OK
OpenAPI contract is up to date.
=== Full local CI parity checks passed ===
```

## Interpretation

This is a deployment-layer review ergonomics slice. It makes the catalog,
detail, and quality-summary review surfaces consistent while preserving the
internal-only, read-only, aggregate-only boundary.
