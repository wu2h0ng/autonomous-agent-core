# ADR-0003 Public Resume API Checkpoint-Read Failure Fix

Date: 2026-06-30
Status: BRANCH-LOCAL IMPLEMENTED AND VERIFIED - NOT MERGED/PUSHED/RELEASED
Repo: `ai-native-business-data-agent-os`
Branch: `codex/agent-runtime-public-resume-api`

## Scope

This follow-up tightens the branch-local public resume API failure path for
checkpoint backend read failures. It does not change resume authorization,
checkpoint fingerprint semantics, successful resume output projection, or the
non-claim boundary around external release.

## Defect

The public resume route checked `checkpoint_store.get(runtime_run_id)` before
calling `AgentRuntime.resume_from_checkpoint(...)`. If the checkpoint backend
raised while reading, the exception bypassed the typed resume error contract and
returned an untyped plain-text HTTP 500. The lower-level runtime resume path had
the same read-exception leak if called directly.

That violated the public resume API contract: every resume failure should be
typed, safe, and free of backend DSNs, credentials, raw args, raw SQL, or tool
output.

## Behavior

- `POST /agent-runtime/runs/{runtime_run_id}/resume` now returns JSON 500 with
  `code="CHECKPOINT_READ_FAILED"` when checkpoint read fails before a snapshot is
  available.
- `AgentRuntime.resume_from_checkpoint(...)` now returns
  `AgentToolResult(status="checkpoint_error",
  error_code="CHECKPOINT_READ_FAILED")` on checkpoint read failure.
- Safe `agent_runtime.checkpoint_resume_failed` trace evidence is written
  without raw exception text or raw resume args.
- Existing `CHECKPOINT_NOT_AVAILABLE`, `CHECKPOINT_NOT_FOUND`,
  `CHECKPOINT_MISMATCH`, and policy-denial semantics are unchanged.

## Red Tests

Added:

```text
tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_checkpoint_read_failure_is_typed_500
tests.unit.test_agent_runtime_replay_boundary.AgentRuntimeReplayBoundaryTest.test_resume_checkpoint_store_read_failure_returns_structured_error
```

Observed RED before implementation:

```text
AssertionError: 'application/json' not found in 'text/plain; charset=utf-8'
AssertionError: resume leaked checkpoint read exception
```

## Verification

Targeted checks after implementation:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  ../../.venv/bin/python -m unittest -q \
  tests.unit.test_agent_runtime_replay_boundary.AgentRuntimeReplayBoundaryTest.test_resume_checkpoint_store_read_failure_returns_structured_error \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_checkpoint_read_failure_is_typed_500
```

Result:

```text
Ran 2 tests
OK
```

Targeted public-resume suite:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  ../../.venv/bin/python -m unittest -q \
  tests.unit.test_agent_runtime_replay_boundary \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_run_response_carries_runtime_checkpoint_ref \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_run_response_omits_runtime_checkpoint_ref_without_checkpoint_store \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_replays_checkpoint_without_rerunning_trusted_loop \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_mismatch_fails_closed_without_raw_args \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_context_mismatch_does_not_echo_untrusted_trace_id \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_without_checkpoint_store_is_service_unavailable \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_checkpoint_read_failure_is_typed_500 \
  tests.unit.test_http_app.HttpAppAuthBoundaryTest.test_api_principal_scope_contract_is_explicit \
  tests.unit.test_http_app.HttpAppAuthBoundaryTest.test_external_report_key_cannot_use_management_surfaces \
  tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema \
  tests.unit.test_openapi_contract.OpenApiContractTest.test_contract_covers_all_trigger_surfaces \
  tests.unit.test_openapi_contract.OpenApiContractTest.test_agent_runtime_resume_contract_is_declared
```

Result:

```text
Ran 23 tests in 0.439s
OK
```

Full verification:

```bash
make ci PYTHON=../../.venv/bin/python
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=../../.venv/bin/python
```

Observed on 2026-06-30:

- ruff clean
- formatting clean (`114 files already formatted`)
- primary unittest discovery: `505` tests OK, `4` skipped
- eval suite: `12` tests OK
- OpenAPI snapshot up to date
- `make ci`: `=== All CI checks passed ===`
- `ci-local-full`: `=== Full local CI parity checks passed ===`

## Non-Claims

This branch remains local. This fix does not merge to main, push, release,
grant external-report resume permission, rerun the Trusted Loop body during
resume, expose raw checkpoint contents, implement full RBAC/DLP, or claim
autonomous-core evidence.
