# P1-09 Knowledge Context Proposal Binding Implementation

Date: 2026-07-03
Branch: `codex/p1-09-knowledge-context-proposal-20260703`
Base: deployment local `main@419c006`
Status: branch-local implemented and full-verified; not pushed, not released

## Scope

This slice closes the next read-side part of the KnowledgeAsset loop.

When a run recalls reviewed/value-backed KnowledgeAssets, the generated
`ActionProposal` now carries the consumed asset ids in `knowledge_context_refs`,
and the `action_proposal` trace event records the same ids.

This makes reviewed knowledge influence the next proposal as auditable context
without changing the evidence path, recommendation text, risk tier, approval
requirement, connector routing, or execution authority.

## Entry Points

- Contract: `ActionProposal.knowledge_context_refs`
- Runtime: `TrustedLoopRuntime.run(...).action_proposal`
- Trace: `TraceEvent(step="action_proposal").payload["knowledge_context_refs"]`

## Boundaries

This is a proposal-context binding only.

It does not expose knowledge refs in external report projection, write feedback,
promote adoption/value, publish KnowledgeAssets, bypass SQL Safety/EvidenceChain,
lower governance, change Approval, or allow R4/R5 automatic execution.

Only safe `asset_id` references are stored on the proposal/trace; KnowledgeAsset
titles/content are not copied into `decision.reason`.

## TDD Evidence

RED:

- After a prior candidate was approved to `ACTIVE`, the next run recalled it but
  the `ActionProposal` had no `knowledge_context_refs`, and the
  `action_proposal` trace event did not bind the recalled asset id.

GREEN:

- The recalled reviewed KnowledgeAsset id appears in
  `ActionProposal.knowledge_context_refs`.
- The same id appears in the `action_proposal` trace event.
- The proposal keeps the original `R2` risk and `approval_required=False` for
  the normal non-side-effecting run.

## Verification

Targeted suite:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest tests.unit.test_knowledge_recall tests.unit.test_trusted_loop tests.unit.test_http_app.HttpDefaultAppRecallTest tests.unit.test_http_app.HttpKnowledgeSearchTest tests.unit.test_governance_decision_seam -v
```

Result: 67 tests OK.

Full branch verification:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Results:

- ruff check passed.
- ruff format check passed.
- primary unittest suite passed: 556 tests OK / 4 skipped.
- eval suite passed: 12 tests OK.
- threshold report passed: 5 golden cases across 8 dimensions met 1.0 thresholds.
- OpenAPI contract check passed.
- PostgreSQL `ci-local-full` parity passed.
