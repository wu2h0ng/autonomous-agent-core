# ADR-0002 Connector Execution Audit Contract v0 — Implementation Log

Date: 2026-06-24
Branch: `codex/durable-action-ledger`

## Scope

Implemented a typed, conservative execution-audit projection for governed connector execution.

This slice hardens the operator approval-execute surface and trace payloads:

- `ConnectorExecutionAudit` contract in `packages/contracts`.
- `ConnectorExecutionSemantics` on `ActionConnectorContract`, so audit defaults are declared by the registered connector contract instead of inferred ad hoc from payload shape.
- `ActionConnectorRegistry.get_execution_semantics()` and runtime audit-default projection through that registry path.
- Safe connector-reported execution fields projected into `connector_executed` and `connector_execution_uncertain` trace events.
- Typed HTTP `ApprovalExecutionAudit` OpenAPI schema for `/approvals/{approval_id}/execute`.
- Regression tests that raw action parameters and secret-like fields do not enter the audit projection.
- Factory wiring that declares `action_record` as `connector_local_ledger` with idempotency/reconciliation semantics.

## Boundaries

This does not claim:

- external-system exactly-once;
- external ACK confirmation;
- durable arbitrary external connector recovery;
- R4/R5 automatic execution;
- external release or merge readiness.

`external_ack_status` defaults to `unknown` for external connector semantics unless a connector explicitly reports otherwise.
`action_record` remains capped at R3 and approval-bound; this contract declaration is a readiness/audit hardening, not an R4/R5 execution unlock.

## RED Checks Observed

- `ConnectorExecutionAudit` import failed before the contract existed.
- External connector `connector_executed` events lacked `durability_scope` before the runtime safe-field projection was extended.
- Contract tests failed to import `ConnectorExecutionSemantics` before connector-level execution defaults existed.
- Minimal external connector execution lacked `durability_scope` before runtime filled audit defaults from the registered connector contract.
- Factory wiring exposed `action_record` with default `connector_response` semantics before the factory registered ledger semantics explicitly.
- The OpenAPI approval-execute response still exposed `execution_audit` as an untyped object before regenerating the snapshot.
- Approval-resume uncertain execution dropped `external_request_id` before the uncertain-audit whitelist was extended.

## Files Changed

- `packages/contracts/src/agent_os_contracts/architecture.py`
- `packages/contracts/src/agent_os_contracts/__init__.py`
- `packages/os_core/src/agent_os_core/trusted_loop.py`
- `packages/os_core/src/agent_os_core/action_connectors/registry.py`
- `apps/api_server/src/agent_os_api/runtime_factory.py`
- `apps/api_server/src/agent_os_api/outcome_service.py`
- `apps/api_server/src/agent_os_api/http_app.py`
- `apps/api_server/openapi.json`
- `tests/unit/test_action_connector.py`
- `tests/unit/test_architecture_contracts.py`
- `tests/unit/test_factory_recall_wiring.py`
- `tests/unit/test_trusted_loop.py`
- `tests/unit/test_trusted_loop_snapshot_rollback.py`
- `tests/eval/test_governed_action_outcome_loop_v0.py`
- `tests/unit/test_openapi_contract.py`
- `README.md`
- `AGENTS.md`
- `apps/api_server/README.md`
