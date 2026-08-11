# P1-27 Knowledge Context Quality Recall Implementation

Date: 2026-07-03
Branch: `codex/p1-27-knowledge-context-quality-recall-20260703`
Layer: deployment
Status: branch-local verified; not pushed; not released

## Scope

Use prior safe correction-channel usage evidence to rerank recalled KnowledgeAssets before binding `ActionProposal.knowledge_context_refs`.

The slice changes only the advisory recall ordering inside `TrustedLoopRuntime.run()`:

- It reads persisted `RunTrace` events already written by the Trusted Loop.
- It counts allowlisted correction usage for recalled asset ids.
- It adds a bounded `context_quality_boost` to the retrieved result score.
- It records safe aggregate `quality_boosts` in the `knowledge_recall` trace event.

## Product Behavior

When two recalled KnowledgeAssets are otherwise semantically tied, the one that has been used in a prior proposal and later received observed outcome/adoption correction evidence is ranked ahead of a merely reviewed active asset.

This is the first narrow product step where history from the feedback/correction path changes the next proposal context selection, without changing the data/evidence/action-governance path.

## Safety Boundaries

This implementation does not:

- expose KnowledgeAsset title/content/full related_knowledge
- expose raw trace ids from historical correction events
- expose raw correction payloads, metric deltas, reasons, or secret-like fields
- mutate KnowledgeAsset lifecycle/version/retrieval/feedback/adoption state
- write feedback or promote adoption/value
- bypass SQL Safety, EvidenceChain, Approval, or connector policy
- alter R4/R5 proposal-only gates
- claim autonomous-core/G10 product validation

## TDD Evidence

RED was observed before implementation:

```text
test_recall_prefers_prior_context_with_observed_outcome_feedback ... FAIL
AssertionError: 'knowledge-merely-active' != 'knowledge-high-quality'
```

After implementation and formatting:

```text
test_recall_prefers_prior_context_with_observed_outcome_feedback ... ok
Ran 1 test in 0.001s
OK
```

Related recall/retrieval/quality suites passed:

```text
Ran 32 tests in 0.131s
OK
```

Branch-local CI passed:

```text
make ci PYTHON=.venv/bin/python3
Ran 588 tests in 3.234s
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

Ran 588 tests in 3.501s
OK
Ran 12 eval tests in 0.003s
OK
OpenAPI contract is up to date.
=== Full local CI parity checks passed ===
```

## Interpretation

This is a deployment-layer governed product capability: outcome/correction evidence can influence the next proposal's knowledge context ordering. It is not an autonomy claim, not causal proof of business value, and not a release claim.
