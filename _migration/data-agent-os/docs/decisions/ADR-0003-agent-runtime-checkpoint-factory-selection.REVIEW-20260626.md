# ADR-0003 Review: Agent Runtime Checkpoint Factory Selection

Date: 2026-06-26
Branch: `codex/agent-runtime-checkpoint-factory-selection`
Base: stacked on `codex/agent-runtime-reviewed-slices-consolidation` at `883997c`
Status: approve for founder/CTO stacked FF decision after the consolidation branch lands first

## Findings

No merge-blocking findings.

## Review Notes

- `ContentCommerceRuntimeFactory.build_agent_checkpoint_store()` keeps backend selection in the product composition layer and returns a `CheckpointStorePort`, so OS Core remains persistence-independent (`apps/api_server/src/agent_os_api/runtime_factory.py:307`).
- `create_app()` injects the selected store into request-scoped runtime adapters for both `POST /runs` and `POST /approvals/{approval_id}/execute`; it does not bypass `RuntimePolicyGate`, approval authority, pause shell, or R4/R5 proposal-only enforcement (`apps/api_server/src/agent_os_api/http_app.py:665`, `apps/api_server/src/agent_os_api/http_app.py:779`).
- SQL checkpoint persistence converts `TrustedLoopOutcome` to an allowlisted summary instead of serializing raw contract/business objects (`packages/persistence/src/agent_os_persistence/mappers.py:161`).
- Coverage includes a postgres factory-selected checkpoint resume across factory/runtime instances and an HTTP `/runs` entrypoint checkpoint write (`tests/unit/test_factory_postgres_store.py:201`, `tests/unit/test_http_app.py:121`).

## Open Questions

- Checkpoint resume output is currently a JSON-safe summary for Trusted Loop outcomes, not a rehydrated `TrustedLoopOutcome` object. That is acceptable for this slice because no public checkpoint resume API is introduced. A future public resume surface needs its own typed contract.
- Merge order matters: this branch is stacked on `codex/agent-runtime-reviewed-slices-consolidation`. Fast-forward that consolidation branch first, then fast-forward this branch, or rebase this branch onto the updated `main` before merge.

## Verification

```bash
git diff --check
/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m ruff check apps/api_server/src/agent_os_api/runtime_factory.py apps/api_server/src/agent_os_api/http_app.py packages/os_core/src/agent_os_core/agent_runtime/__init__.py packages/persistence/src/agent_os_persistence/mappers.py tests/unit/test_factory_postgres_store.py tests/unit/test_http_app.py
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest tests.unit.test_factory_postgres_store tests.unit.test_http_app tests.unit.test_agent_runtime_sql_checkpoint tests.unit.test_agent_runtime_replay_boundary tests.unit.test_persistence -v
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result:

- diff check passed.
- focused ruff passed.
- affected suite passed: 77 tests OK.
- `make ci` passed: ruff, format check, 458 tests, 12 eval tests, and OpenAPI contract check.
- `ci-local-full` passed against disposable PostgreSQL.

## Required Changes

None for this slice.

## Approval Status

Approved for a founder/CTO merge decision with the explicit condition that no release/external capability claim is made and the stacked merge order is preserved.
