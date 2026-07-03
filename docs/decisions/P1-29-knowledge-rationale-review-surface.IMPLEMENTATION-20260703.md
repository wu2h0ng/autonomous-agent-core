# P1-29 Knowledge Rationale Review Surface Implementation

Date: 2026-07-03
Branch: `codex/p1-29-knowledge-rationale-review-surface-20260703`
Layer: deployment
Status: branch-local verified; not merged; not pushed; not released

## Scope

Expose safe review rationale codes on the internal KnowledgeAsset quality review
surface so reviewers can understand why a KnowledgeAsset is in a given review
state without reading raw traces or KnowledgeAsset content.

P1-28 made per-run decision context rationale visible to internal clients.
P1-29 makes the review queue itself carry a stable, typed rationale surface:

- `GET /knowledge/assets/quality-summary`
- `KnowledgeAssetQualitySummaryItem.review_rationale_codes`

## Product Behavior

Each quality-summary item now includes one allowlisted rationale code derived
from the existing safe quality status:

- `unused_context_candidate`
- `proposal_context_needs_outcome`
- `outcome_supported_context`
- `adoption_supported_context`

The codes are derived from aggregate usage/correction state already exposed by
the quality summary. They do not expose trace event payloads, KnowledgeAsset
title/content, usage trace ids, raw reasons, score breakdowns, correction
payloads, metric deltas, or secret-like fields.

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
KeyError: 'review_rationale_codes'
AssertionError: Items in the second set but not the first:
'review_rationale_codes'
```

Targeted tests passed after implementation:

```text
Ran 3 tests in 0.270s
OK
```

Related service/API/OpenAPI suite passed:

```text
Ran 9 tests in 0.376s
OK
```

Branch-local CI passed:

```text
make ci PYTHON=.venv/bin/python3
Ran 590 tests in 3.329s
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

Ran 590 tests in 3.493s
OK
Ran 12 eval tests in 0.004s
OK
OpenAPI contract is up to date.
=== Full local CI parity checks passed ===
```

## Interpretation

This is a deployment-layer product affordance for internal KnowledgeAsset
review. It improves the review queue's auditability and actionability while
preserving the product/process boundary: this is not an autonomy claim, not
causal proof of value, and not a release claim.
