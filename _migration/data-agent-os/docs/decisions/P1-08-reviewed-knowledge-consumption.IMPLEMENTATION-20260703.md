# P1-08 Reviewed Knowledge Consumption Implementation

Date: 2026-07-03
Branch: `codex/p1-08-active-knowledge-consumption-20260703`
Base: deployment local `main@02f4f26`
Status: branch-local implemented and verified; not pushed, not released

## Scope

This slice tightens the read side of KnowledgeAsset consumption.

Default knowledge retrieval now consumes only:

- human-reviewed `ACTIVE` KnowledgeAssets, or
- value-backed KnowledgeAssets with external `adopted` outcome.

Unreviewed DRAFT candidates and DEPRECATED/rejected review outputs remain stored and auditable, but they are no longer consumed by default by `/knowledge/search` or runtime `related_knowledge` recall.

Explicit `KnowledgeQuery.lifecycle_state` still returns that lifecycle state for internal/debug uses; the default consumption path is the guarded path.

## Entry Points

- In-memory retrieval: `InMemoryKnowledgeRetriever.search`
- SQL retrieval: `SqlKnowledgeRetriever.search`
- Runtime recall: `TrustedLoopRuntime.run(...).related_knowledge`
- HTTP search: `GET /knowledge/search`
- HTTP run response recall: `POST /runs`

## Boundaries

This is a read-side consumption guard only.

It does not change KnowledgeAsset creation, review actions, adoption ingestion, feedback writing, publish workflow, production telemetry export, autonomous-core validation, or R4/R5 execution behavior.

## TDD Evidence

RED:

- Default in-memory retrieval returned `deprecated`, `active`, and `draft` together.
- Runtime second-run recall consumed the first run's unreviewed DRAFT candidate.
- SQL retrieval returned DRAFT/DEPRECATED candidates by default.

GREEN:

- Default retrieval returns only `ACTIVE` or externally adopted value-backed assets.
- Explicit lifecycle queries still expose DRAFT records when requested.
- Runtime recall ignores unreviewed DRAFT candidates and recalls reviewed ACTIVE knowledge.
- HTTP `/knowledge/search` and `/runs` recall ignore raw DRAFT candidates, then consume them after internal review approval.
- Adoption-backed knowledge remains searchable through the existing value-promotion path.

## Verification

Targeted suite:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest tests.unit.test_knowledge_retrieval tests.unit.test_knowledge_recall tests.unit.test_knowledge_retrieval_sql tests.unit.test_factory_recall_wiring tests.unit.test_http_app.HttpDefaultAppRecallTest tests.unit.test_http_app.HttpKnowledgeSearchTest -v
```

Result: 42 tests OK.

Full branch verification:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Results:

- ruff check passed.
- ruff format check passed.
- primary unittest suite passed: 555 tests OK / 4 skipped.
- eval suite passed: 12 tests OK.
- threshold report passed: 5 golden cases across 8 dimensions met 1.0 thresholds.
- OpenAPI contract check passed.
- PostgreSQL `ci-local-full` parity passed.
