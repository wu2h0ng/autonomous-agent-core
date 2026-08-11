# P1-28 Knowledge Context Rationale Implementation

Date: 2026-07-03
Branch: `codex/p1-28-knowledge-context-rationale-20260703`
Layer: deployment
Status: branch-local verified; not pushed; not released

## Scope

Project safe, internal-only rationale for the KnowledgeAssets bound into a proposal.

P1-27 made prior correction/outcome usage affect recall ordering. P1-28 makes that product-visible to internal clients through:

- `user_result.decision.knowledge_context_rationale`
- `KnowledgeContextRationaleItem` OpenAPI schema

Each rationale item contains only:

- `asset_id`
- `score`
- `context_quality_boost`
- `reason_code`

## Product Behavior

Internal users can now see why a KnowledgeAsset was brought into the current decision context:

- `retrieved_reviewed_context` for normal reviewed recall
- `prior_outcome_or_adoption_context` when prior correction/adoption usage contributed a boost

External audience projection still returns an empty rationale list.

## Safety Boundaries

This projection does not expose:

- KnowledgeAsset title/content/full related_knowledge
- source trace ids or historical trace ids
- raw score breakdown fields
- raw correction payloads, metric deltas, reasons, or secret-like fields

It does not mutate KnowledgeAsset lifecycle/version/retrieval/feedback/adoption state, lower governance, bypass SQL Safety/EvidenceChain/Approval, promote adoption/value, write feedback, or enable R4/R5 automatic execution.

## TDD Evidence

RED was observed before implementation:

```text
KeyError: 'knowledge_context_rationale'
AssertionError: 'knowledge_context_rationale' not found in UserResultDecision.required
```

Targeted tests passed after implementation:

```text
Ran 3 tests in 0.217s
OK
```

Related service/API/OpenAPI suite passed:

```text
Ran 18 tests in 0.420s
OK
```

Branch-local CI passed:

```text
make ci PYTHON=.venv/bin/python3
Ran 589 tests in 3.683s
OK (skipped=4)
Ran 12 eval tests in 0.005s
OK
OpenAPI contract is up to date.
=== All CI checks passed ===
```

PostgreSQL local parity passed:

```text
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full PYTHON=.venv/bin/python3

Ran 589 tests in 3.663s
OK
Ran 12 eval tests in 0.004s
OK
OpenAPI contract is up to date.
=== Full local CI parity checks passed ===
```

## Interpretation

This is a deployment-layer product affordance: internal users can inspect why historical knowledge influenced a proposal context. It is not a causality/value claim, not an autonomous-core/G10 product validation, and not a release claim.
