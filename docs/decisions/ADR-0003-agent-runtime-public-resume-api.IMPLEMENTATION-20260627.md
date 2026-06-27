# ADR-0003 Implementation: Agent Runtime Public Resume API

Date: 2026-06-27
Status: BRANCH-LOCAL IMPLEMENTATION VERIFIED ON `codex/agent-runtime-public-resume-api` - NOT MERGED/PUSHED/RELEASED
Repo: `ai-native-business-data-agent-os`

## Purpose

Close the next narrow Agent Runtime recoverability gap by exposing a safe,
internal-only HTTP resume surface for the existing fingerprint-bound checkpoint
boundary.

This is not a workflow retry engine, not automatic business-action execution,
not an external release, and not an autonomy claim.

## Scope

Implemented branch-local:

- `POST /runs` now returns an internal-only `runtime_checkpoint_ref` with
  runtime `run_id`, runtime `trace_id`, `tool_name`, and `call_id`.
- external report-key projections force `runtime_checkpoint_ref = null`.
- `POST /agent-runtime/runs/{runtime_run_id}/resume` reconstructs the same
  `trusted_loop.evaluate` call fingerprint from the caller-supplied
  `runtime_trace_id`, `question`, and `parameters`.
- resume calls go through `AgentRuntime.resume_from_checkpoint`, which now
  rechecks `RuntimePolicyGate` before returning a stored checkpoint result.
- successful resume returns only `RuntimeResumeResponse` with a safe
  `output_ref`, never raw tool output or original request parameters.
- successful resume appends safe `agent_runtime.checkpoint_resume_*` events to
  the persisted business `RunTrace`.
- checkpoint mismatch, missing checkpoint, and policy denial are fail-closed
  with safe HTTP errors.

## Call Path

```text
POST /runs
  -> request-scoped AgentRunContext
  -> TrustedLoopAgentRuntimeAdapter
  -> AgentRuntime.invoke_tool
  -> factory-selected checkpoint store
  -> internal runtime_checkpoint_ref in RunResponse

POST /agent-runtime/runs/{runtime_run_id}/resume
  -> internal API scope `runtime:resume`
  -> request-scoped AgentRunContext
  -> TrustedLoopAgentRuntimeAdapter.runtime.resume_from_checkpoint
  -> RuntimePolicyGate recheck
  -> fingerprint comparison
  -> safe RuntimeResumeResponse
  -> safe RunTrace append on successful resume
```

## Failure Paths

- external report key cannot call the resume route (`403`).
- paused shell denies resume before returning a checkpoint result
  (`DENY_PAUSED`).
- changed call args fail as `CHECKPOINT_MISMATCH` without tool execution and
  without raw arg echo.
- changed or untrusted `runtime_trace_id` fails before runtime context
  construction and does not echo the caller-supplied trace id into the HTTP
  error or runtime trace events.
- missing checkpoint returns a safe `CHECKPOINT_NOT_FOUND` error.
- missing checkpoint store returns `CHECKPOINT_NOT_AVAILABLE` as a `503`
  configuration failure.

## Verification

Targeted RED was observed before implementation:

- paused `resume_from_checkpoint` returned the previous `ok` checkpoint result;
- `RunResponse.runtime_checkpoint_ref` was missing;
- resume route and `runtime:resume` scope were missing.

Additional hardening RED was observed during implementation:

- mismatched caller-supplied `runtime_trace_id` was echoed in the error/trace
  path before snapshot prevalidation;
- a missing checkpoint store returned a generic conflict instead of the
  configuration-specific `503 CHECKPOINT_NOT_AVAILABLE` failure.

Targeted GREEN after implementation:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
  /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python \
  -m unittest \
  tests.unit.test_agent_runtime_replay_boundary.AgentRuntimeReplayBoundaryTest.test_resume_respects_paused_shell_before_returning_checkpoint \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_run_response_carries_runtime_checkpoint_ref \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_replays_checkpoint_without_rerunning_trusted_loop \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_mismatch_fails_closed_without_raw_args \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_context_mismatch_does_not_echo_untrusted_trace_id \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_without_checkpoint_store_is_service_unavailable \
  tests.unit.test_http_app.HttpAppAuthBoundaryTest.test_api_principal_scope_contract_is_explicit \
  tests.unit.test_http_app.HttpAppAuthBoundaryTest.test_external_report_key_cannot_use_management_surfaces \
  tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema \
  tests.unit.test_openapi_contract.OpenApiContractTest.test_contract_covers_all_trigger_surfaces \
  tests.unit.test_openapi_contract.OpenApiContractTest.test_agent_runtime_resume_contract_is_declared \
  -v
```

Observed: `11` tests OK.

Full branch verification also passed:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Observed:

- ruff clean
- formatting clean (`114 files already formatted`)
- primary unittest discovery: `501` tests OK, `4` skipped
- eval suite: `12` tests OK
- OpenAPI snapshot up to date
- `=== All CI checks passed ===`

```bash
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Observed:

- ruff clean
- formatting clean
- primary unittest discovery: `501` tests OK
- eval suite: `12` tests OK
- OpenAPI snapshot up to date
- `=== Full local CI parity checks passed ===`

## Boundaries

This slice does not:

- push or release the route;
- grant external report principals resume capability;
- expose raw args, raw SQL, raw tool output, or connector payloads;
- rerun the Trusted Loop body during resume;
- bypass SQL Safety, EvidenceChain, Approval, or Trace;
- implement automatic R4/R5 execution;
- implement true wall-clock interruption, async cancellation, or workflow
  concurrency;
- import external agent frameworks or autonomous-core code.

## Next Gate

Require review and explicit founder/CTO authorization before any local-main
merge. Push and release remain separate gates.
