# P1-32 Knowledge Detail Review State Implementation

Date: 2026-07-03
Branch: `codex/p1-29-knowledge-rationale-review-surface-20260703`
Layer: deployment
Status: branch-local verified; not merged; not pushed; not released

## Scope

Make the internal KnowledgeAsset detail surface self-contained for review
triage by adding the same safe review-state fields that the collection-level
quality summary already exposes.

P1-32 adds to `GET /knowledge/assets/{asset_id}`:

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
same allowlisted status mappings used by `GET /knowledge/assets/quality-summary`.

## Product Behavior

An internal reviewer can open a single KnowledgeAsset detail view and see why
that asset needs review, feedback follow-up, monitoring, or publish
consideration without joining the collection summary and decision-quality
routes manually.

The route remains read-only and internal-only. It does not return
`usage_trace_ids`; the detail view keeps only safe aggregate counts and
allowlisted rationale codes.

## Safety Boundaries

This slice does not:

- expose the detail route to `external_report`;
- expose raw trace events, raw trace payloads, raw reasons, score breakdowns,
  correction payloads, metric deltas, or secret-like fields;
- expose `usage_trace_ids` from the decision-quality aggregate on the detail
  response;
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
AssertionError: required schema fields did not include review-state fields
```

Targeted tests passed after implementation:

```text
Ran 3 tests in 0.226s
OK
```

Related detail/quality/OpenAPI suite passed:

```text
Ran 16 tests in 0.439s
OK
```

Branch-local CI passed after one mechanical format run:

```text
make ci PYTHON=.venv/bin/python3
Ran 591 tests in 3.228s
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

Ran 591 tests in 3.498s
OK
Ran 12 eval tests in 0.004s
OK
OpenAPI contract is up to date.
=== Full local CI parity checks passed ===
```

## Interpretation

This is a deployment-layer review ergonomics slice. It makes a single
KnowledgeAsset detail response sufficient for internal review triage while
preserving the product/process boundary and existing governance gates.
