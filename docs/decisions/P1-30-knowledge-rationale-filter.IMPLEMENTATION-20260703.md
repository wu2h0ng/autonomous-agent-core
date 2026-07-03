# P1-30 Knowledge Rationale Filter Implementation

Date: 2026-07-03
Branch: `codex/p1-29-knowledge-rationale-review-surface-20260703`
Layer: deployment
Status: branch-local verified; not merged; not pushed; not released

## Scope

Make the internal KnowledgeAsset quality review queue filterable by the safe
`review_rationale_codes` introduced in P1-29.

P1-30 adds:

- `GET /knowledge/assets/quality-summary?review_rationale_code=...`
- `KnowledgeAssetQualitySummaryResponse.review_rationale_code_filter`
- OpenAPI enum coverage for the `review_rationale_code` query parameter

Allowed filter values:

- `unused_context_candidate`
- `proposal_context_needs_outcome`
- `outcome_supported_context`
- `adoption_supported_context`

## Product Behavior

Internal reviewers can now focus the queue by the reason an asset needs review
or follow-up. The filter is derived from existing aggregate quality status and
the P1-29 allowlisted rationale codes. It does not read raw trace payloads,
KnowledgeAsset content, usage trace ids, raw reasons, score breakdowns, or
correction payloads.

Invalid `review_rationale_code` values fail closed with the existing
`KNOWLEDGE_QUALITY_SUMMARY_INVALID_REQUEST` response.

## Safety Boundaries

This slice is internal and read-only. It does not:

- expose the quality-summary route to `external_report`;
- expose KnowledgeAsset title/content/full related_knowledge;
- expose raw historical trace ids or raw trace payloads;
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
TypeError: knowledge_asset_quality_summary_service() got an unexpected keyword argument 'review_rationale_code'
KeyError: 'review_rationale_code_filter'
StopIteration
```

Targeted tests passed after implementation:

```text
Ran 3 tests in 0.243s
OK
```

Related service/API/OpenAPI suite passed:

```text
Ran 9 tests in 0.402s
OK
```

Branch-local CI passed after formatting:

```text
make ci PYTHON=.venv/bin/python3
Ran 590 tests in 3.309s
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

Ran 590 tests in 3.609s
OK
Ran 12 eval tests in 0.003s
OK
OpenAPI contract is up to date.
=== Full local CI parity checks passed ===
```

## Interpretation

This is a deployment-layer review-queue ergonomics slice. It makes the existing
safe rationale surface actionable for internal reviewers without expanding
external reporting, lifecycle mutation, value promotion, or execution authority.
