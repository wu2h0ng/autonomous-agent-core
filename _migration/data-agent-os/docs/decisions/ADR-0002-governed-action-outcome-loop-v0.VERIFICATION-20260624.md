# ADR-0002 Remediation Verification — 2026-06-24

Branch: `codex/durable-action-ledger`

Freshness note: this is the historical verification record for the H1/M1/M2 remediation
slice. It is not the current test-count source. Later connector execution-audit and
connector-declared execution-semantics hardening raised the current verified count to
414 tests OK; use `docs/CURRENT_STATE.yaml` and
`docs/decisions/ADR-0002-connector-execution-audit-contract-v0.VERIFICATION-20260624.md`
for the current live count.

## RED Checks Observed

- M1 public-external redaction test failed before implementation because `redaction.applied` was `False` for public external metrics.
- H1 two-reclaimer race test failed before implementation with two winners: both stale reclaimers returned a claimed context.
- M2 was a coverage gap over already-existing 503 behavior; the added test passed once invoked with the correct project `PYTHONPATH`.

## Targeted Verification

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:apps/api_server/src:action_connectors \
  .venv/bin/python -m unittest tests.unit.test_persistence.PersistenceRepositoriesTest.test_approval_context_stale_reclaim_allows_only_one_cross_process_winner -v
```

Result: OK.

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:apps/api_server/src:action_connectors \
  .venv/bin/python -m unittest tests.unit.test_outcome_service.RunServiceTest.test_external_audience_keeps_public_metric_details -v
```

Result: OK.

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:apps/api_server/src:action_connectors \
  .venv/bin/python -m unittest tests.unit.test_http_app.HttpAppAuthBoundaryTest.test_unconfigured_operator_key_returns_503 -v
```

Result: OK.

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:apps/api_server/src:action_connectors \
  .venv/bin/python -m unittest tests.unit.test_http_app tests.unit.test_outcome_service tests.unit.test_persistence tests.unit.test_factory_postgres_store -v
```

Result: 74 tests OK.

## Full Verification

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result:

- ruff check clean.
- ruff format check clean.
- primary unittest discover: 404 tests OK, 4 skipped.
- eval suite: 12 tests OK.
- OpenAPI contract check up to date.

```bash
AGENT_OS_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:15432/agent_os_test \
  make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result: Full local CI parity checks passed.

Environment note: host `127.0.0.1:5432` was a Homebrew PostgreSQL instance, not the existing `multica-postgres-1` container. A separate disposable test container named `agent-os-test-postgres` was started on host port `15432` for `ci-local-full`.
