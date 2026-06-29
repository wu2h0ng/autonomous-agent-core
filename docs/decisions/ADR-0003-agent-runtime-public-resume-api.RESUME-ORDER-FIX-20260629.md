# ADR-0003 Public Resume API Resume-Order Fix

Date: 2026-06-29
Status: BRANCH-LOCAL IMPLEMENTED AND VERIFIED - NOT MERGED/PUSHED/RELEASED
Repo: `ai-native-business-data-agent-os`
Branch: `codex/agent-runtime-public-resume-api`

## Scope

This follow-up tightens the branch-local public resume API slice by aligning
`AgentRuntime.resume_from_checkpoint()` with the checkpoint integrity order:

1. require checkpoint store and `run_id`;
2. require registered tool spec;
3. require an existing checkpoint and stored result;
4. verify checkpoint metadata for call/context/tool-spec fingerprints;
5. only then rerun the current `RuntimePolicyGate` before returning the stored
   result.

The prior branch-local ordering reran `RuntimePolicyGate` before loading and
validating the stored checkpoint. That meant a paused shell could mask a call
fingerprint mismatch as `DENY_PAUSED`. For a resume API, integrity failures must
stay visible as typed checkpoint failures before current policy state is used to
deny an otherwise matching replay.

## Behavior

- A matching checkpoint still returns the stored result without rerunning the
  Trusted Loop body.
- A matching checkpoint under a paused shell still returns `DENY_PAUSED` and
  emits `agent_runtime.checkpoint_resume_failed`.
- A mismatched checkpoint under a paused shell now returns
  `CHECKPOINT_MISMATCH`, not `DENY_PAUSED`.
- Raw resume args remain absent from trace events and error payloads.
- HTTP resume behavior remains unchanged for missing checkpoints because the
  route checks checkpoint existence before constructing the runtime resume call.

## Red Test

Added:

```text
tests.unit.test_agent_runtime_replay_boundary.AgentRuntimeReplayBoundaryTest.test_resume_mismatch_is_not_masked_by_paused_shell
```

After correcting a test-fixture typo, the test failed on the previous behavior:

```text
AssertionError: 'denied' != 'validation_error'
```

That proved the paused policy denial was masking the checkpoint mismatch.

## Implementation

`packages/os_core/src/agent_os_core/agent_runtime/__init__.py` now moves the
resume policy recheck after checkpoint lookup and fingerprint mismatch checks.
The existing `agent_runtime.policy_denied` trace event is preserved for a
matching checkpoint that is denied by current policy.

## Verification

Focused red/green checks:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python \
  -m unittest -q \
  tests.unit.test_agent_runtime_replay_boundary.AgentRuntimeReplayBoundaryTest.test_resume_mismatch_is_not_masked_by_paused_shell
```

Result after implementation:

```text
Ran 1 test in 0.000s
OK
```

Existing paused matching-checkpoint regression:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python \
  -m unittest -q \
  tests.unit.test_agent_runtime_replay_boundary.AgentRuntimeReplayBoundaryTest.test_resume_respects_paused_shell_before_returning_checkpoint
```

Result:

```text
Ran 1 test in 0.000s
OK
```

Targeted public-resume suite:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python \
  -m unittest -q \
  tests.unit.test_agent_runtime_replay_boundary \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_replays_checkpoint_without_rerunning_trusted_loop \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_mismatch_fails_closed_without_raw_args \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_context_mismatch_does_not_echo_untrusted_trace_id \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_without_checkpoint_store_is_service_unavailable \
  tests.unit.test_openapi_contract.OpenApiContractTest.test_agent_runtime_resume_contract_is_declared
```

Result:

```text
Ran 15 tests in 0.222s
OK
```

Full local CI:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result:

```text
All checks passed!
114 files already formatted
Ran 503 tests in 1.259s
OK (skipped=4)
Ran 12 tests in 0.004s
OK
OpenAPI contract is up to date.
=== All CI checks passed ===
```

PostgreSQL parity:

```bash
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full \
  PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result:

```text
All checks passed!
114 files already formatted
Ran 503 tests in 1.531s
OK
Ran 12 tests in 0.004s
OK
OpenAPI contract is up to date.
=== All CI checks passed ===
=== Full local CI parity checks passed ===
```

## Non-Claims

This fix does not merge the branch, push, release externally, add public
external access, implement wall-clock cancellation, add workflow orchestration,
authorize automatic R4/R5 execution, or claim autonomous-core evidence.

## Gate Outcome

Outcome: BRANCH-LOCAL ORDER FIX VERIFIED.

Founder/CTO authorization is still required before any local-main merge. Push
and external release remain separate gates.
