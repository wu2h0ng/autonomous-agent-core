# ADR-0003 Implementation Log: Agent Runtime Checkpoint Factory Selection

Date: 2026-06-26
Branch: `codex/agent-runtime-checkpoint-factory-selection`
Base: stacked on `codex/agent-runtime-reviewed-slices-consolidation` at `883997c`
Status: implementation complete; affected-suite, `make ci`, and `ci-local-full` passed

## Scope

This slice wires the existing Agent Runtime checkpoint boundary into the product composition layer:

- `ContentCommerceRuntimeFactory.build_agent_checkpoint_store()` selects a factory-scoped `InMemoryCheckpointStore` for `memory` and `SqlAgentCheckpointStore` for `postgres`.
- `create_app()` stores the selected checkpoint store on `app.state.agent_checkpoint_store`.
- `POST /runs` and `POST /approvals/{approval_id}/execute` inject that store into their request-scoped Agent Runtime adapters.
- `TrustedLoopAgentRuntimeAdapter` and `TrustedLoopApprovalExecutionRuntimeAdapter` accept an optional `CheckpointStorePort` without importing persistence into OS Core.

## Safety Boundary

The SQL checkpoint mapper does not persist raw `TrustedLoopOutcome` objects. It stores an allowlisted summary containing status and stable identifiers such as `trace_id`, `evidence_chain_id`, metric names, row count, action proposal id, and approval id.

This preserves the existing rule that runtime trace/checkpoint surfaces must not become raw business-payload dumps.

## Tests

New regression coverage:

- Factory-selected postgres checkpoint store persists a `trusted_loop.evaluate` Agent Runtime checkpoint across runtime/factory instances and resumes without re-executing the tool body.
- HTTP `POST /runs` writes an Agent Runtime checkpoint from the real route entry point.

Affected suite run:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest tests.unit.test_factory_postgres_store tests.unit.test_http_app tests.unit.test_agent_runtime_sql_checkpoint tests.unit.test_agent_runtime_replay_boundary tests.unit.test_persistence -v
```

Result: 77 tests OK.

Full branch-local verification:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result:

- `make ci` passed: ruff, format check, 458 tests, 12 eval tests, and OpenAPI contract check.
- `ci-local-full` passed against the disposable PostgreSQL URL above.

## Non-Claims

This slice does not add a public checkpoint resume API, workflow engine, concurrent graph runtime, arbitrary durable replay, external-system exactly-once behavior, autonomous-core adoption, or automatic R4/R5 execution.
