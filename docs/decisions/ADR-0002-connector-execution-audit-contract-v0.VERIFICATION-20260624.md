# ADR-0002 Connector Execution Audit Contract v0 — Verification

Date: 2026-06-24
Branch: `codex/durable-action-ledger`

## RED Checks Observed

```bash
.venv/bin/python -m unittest tests.unit.test_architecture_contracts -v
```

Result before implementation: failed to import `ConnectorExecutionAudit`.

```bash
.venv/bin/python -m unittest \
  tests.unit.test_trusted_loop.TrustedLoopGovernanceTest.test_external_connector_execution_audit_uses_safe_reported_fields_only -v
```

Result before implementation: failed with missing `durability_scope` in the `connector_executed` event.

```bash
PYTHONPATH=apps/api_server/src:packages/contracts/src:packages/os_core/src:packages/persistence/src:action_connectors \
  .venv/bin/python -m unittest \
  tests.unit.test_openapi_contract.OpenApiContractTest.test_approval_execution_contract_is_declared -v
```

Result before OpenAPI regeneration: failed because `execution_audit` was still an untyped object in the snapshot.

```bash
.venv/bin/python -m unittest \
  tests.unit.test_trusted_loop_snapshot_rollback.TrustedLoopSnapshotTest.test_approval_resume_persists_external_uncertain_audit_without_raw_payloads -v
```

Result before uncertain-audit whitelist hardening: failed with missing `external_request_id`.

## Targeted Verification

```bash
.venv/bin/python -m unittest tests.unit.test_architecture_contracts tests.unit.test_trusted_loop -v
```

Result: 18 tests OK.

```bash
PYTHONPATH=apps/api_server/src:packages/contracts/src:packages/os_core/src:packages/persistence/src:action_connectors \
  .venv/bin/python -m unittest \
  tests.unit.test_openapi_contract \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_approval_execute_endpoint_runs_approval_bound_action -v
```

Result: 8 tests OK.

```bash
.venv/bin/python -m unittest tests.unit.test_trusted_loop_snapshot_rollback -v
```

Result: 16 tests OK.

## Full Verification

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result:

- ruff check clean.
- ruff format check clean.
- primary unittest discover: 410 tests OK, 4 skipped.
- eval suite: 12 tests OK.
- OpenAPI contract check up to date.

```bash
AGENT_OS_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:15432/agent_os_test \
  make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result: full local CI parity checks passed.

Environment note: used the disposable local PostgreSQL test database on `127.0.0.1:15432/agent_os_test`.

