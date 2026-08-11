# ADR-0003 Agent Runtime Reviewed Slices Consolidation Review

Date: 2026-06-26
Branch: `codex/agent-runtime-reviewed-slices-consolidation`
Base: local deployment `main` at `3249c36`
Verdict: APPROVE FOR FOUNDER/CTO FF DECISION

## Scope

This consolidation branch combines two previously reviewed ADR-0003 runtime slices without changing deployment `main`:

- Successful `POST /runs` runtime-envelope events are persisted into queryable `RunTrace` records using allowlisted `agent_runtime.*` metadata only.
- `POST /approvals/{approval_id}/execute` enters a narrow `TrustedLoopApprovalExecutionRuntimeAdapter` before executing approval-bound actions, preserving existing `ApprovalRuntime` and `ApprovalContextStore` authority.

The consolidation resolved overlapping documentation and HTTP/runtime files from:

- `codex/agent-runtime-success-trace-bridge-current`
- `codex/agent-runtime-approval-execute-envelope`

## Review Checks

- No raw request parameters or raw tool output are newly persisted by the success trace bridge.
- Approval execution keeps `X-Operator-Key` auth, original approval-context binding, existing 404/409 response semantics, and R4/R5 proposal-only enforcement.
- Paused-shell approval execution is denied before `agent_runtime.tool_started` and before connector writes.
- OS Core remains self-developed and does not add external agent framework runtime dependencies.
- Consolidation did not merge or push deployment `main`.

## Verification

Commands run on branch `codex/agent-runtime-reviewed-slices-consolidation`:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest tests.unit.test_http_app tests.unit.test_outcome_service tests.unit.test_agent_runtime_policy tests.unit.test_agent_runtime_tools tests.integration.test_trusted_loop_agent_runtime_adapter -v
```

Result: 80 tests OK.

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result: ruff OK, format check OK, 456 tests OK with 4 skipped, 12 eval tests OK, OpenAPI contract up to date.

```bash
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result: full local CI parity checks passed with the same test/eval/OpenAPI counts.

## Remaining Gate

This review approves the consolidation branch for founder/CTO fast-forward merge decision only. It does not authorize external release, push to origin, automatic R4/R5 execution, full workflow replacement, autonomous-core adoption, production UI, full RBAC/DLP, tenant isolation, or external-system exactly-once claims.
