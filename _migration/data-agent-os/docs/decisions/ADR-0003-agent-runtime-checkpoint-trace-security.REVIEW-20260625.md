# ADR-0003 Agent Runtime Checkpoint/Trace Security Review

- Date: 2026-06-25
- Branch reviewed: `codex/runtime-checkpoint-trace-security`
- Base: `main` at `77c7b07`
- Head after remediation: branch head after this review document lands
- Scope: focused merge-prep review for runtime checkpoint/trace hardening before A7 can clear
- Status: approved after remediation and verification

## Verdict

**APPROVED FOR FOUNDER/CTO FF DECISION.**

The review found one real issue and it has a targeted red/green fix. No remaining merge blocker was found in the runtime checkpoint/trace hardening branch.

## Finding

### [MEDIUM] Checkpoint failure masked pre-execution policy denial

`AgentRuntime.invoke_tool(...)` attempted checkpoint persistence for every result returned by `_invoke_tool(...)`, including pre-execution policy denials and validation failures. If the checkpoint store failed, the runtime rewrote the original result into `checkpoint_error`.

Concrete bad case:

- R5 non-proposal action correctly denied as `DENY_HIGH_RISK_EXECUTION`;
- tool body not executed;
- failing checkpoint store rewrote the returned result to `checkpoint_error`;
- caller lost the security-relevant denial code.

This did not permit R4/R5 execution, but it weakened auditability and made the policy gate less transparent.

## Remediation

Added failing regression:

- `tests/unit/test_agent_runtime_replay_boundary.py::AgentRuntimeReplayBoundaryTest::test_checkpoint_store_failure_does_not_mask_policy_denial`

The red failure showed:

```text
AssertionError: 'checkpoint_error' != 'denied'
```

Implementation:

- `AgentRuntime.invoke_tool(...)` now attempts checkpoint persistence only when result status is `ok` or `tool_error`, the statuses that prove the tool body has started.
- Pre-execution `denied` and `validation_error` results remain authoritative and are not rewritten by checkpoint persistence failures.

## Remaining Non-Blocking Notes

- The current default `AgentRunContext.risk_ceiling` remains `R5`. A conservative per-principal default such as `R3` is a founder-reserved/product policy decision for live wiring, not a blocker for this branch because non-proposal R4/R5 execution remains denied.
- `SqlAgentCheckpointStore` persists recovery payloads, not safe trace payloads. Before production factory/API exposure, a later ADR must decide retention, encryption, tenant isolation, and operator-only projection.
- This branch still does not wire Agent Runtime into the live HTTP path. Packet A Slice 0 must prove that separately through endpoint tests.

## Verification

Red/green evidence:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src \
  .venv/bin/python -m unittest \
  tests.unit.test_agent_runtime_replay_boundary.AgentRuntimeReplayBoundaryTest.test_checkpoint_store_failure_does_not_mask_policy_denial -v

Before fix: failed with 'checkpoint_error' != 'denied'
After fix: 1 test OK
```

Targeted runtime suite:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src \
  .venv/bin/python -m unittest \
  tests.unit.test_agent_runtime_policy \
  tests.unit.test_agent_runtime_tools \
  tests.unit.test_agent_runtime_trace \
  tests.unit.test_agent_runtime_replay_boundary \
  tests.unit.test_agent_runtime_sql_checkpoint \
  tests.unit.test_persistence.PersistenceRepositoriesTest.test_agent_runtime_checkpoint_round_trip_and_rewrite \
  tests.unit.test_migrations_cover_schema -v

Result: 32 tests OK
```

Full local gates:

```text
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python

Result: 448 tests OK, 4 skipped; 12 eval tests OK; OpenAPI contract is up to date.

AGENT_OS_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:15432/agent_os_test \
  make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python

Result: full local CI parity checks passed.
```

Mechanical checks:

```text
git diff --check

Result: clean
```

## Gate Result

A7 can clear if founder/CTO approves:

1. Fast-forward `main` to `codex/runtime-checkpoint-trace-security`.
2. Mark `codex/runtime-durable-checkpoint-store` as superseded.
3. Keep non-runtime integration/workspace branches parked.
4. Create `codex/agent-runtime-live-wiring` from the updated `main`.
