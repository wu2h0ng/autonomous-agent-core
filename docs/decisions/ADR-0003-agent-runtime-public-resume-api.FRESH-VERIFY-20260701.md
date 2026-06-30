# ADR-0003 Public Resume API Fresh Verification

Date: 2026-07-01
Status: BRANCH-LOCAL FRESH VERIFICATION - NOT MERGED/PUSHED/RELEASED
Repo: `ai-native-business-data-agent-os`
Branch: `codex/agent-runtime-public-resume-api`
Verified runtime source head: `9f5dbf9 fix(runtime): type public resume checkpoint read failures`

## Scope

This record refreshes verification for the branch-local Agent Runtime public
resume API slice after re-reading the live branch and current implementation.

The verified branch-local capability remains:

- internal-only `POST /agent-runtime/runs/{runtime_run_id}/resume`;
- `runtime:resume` scope on the internal API principal only;
- internal `POST /runs` `runtime_checkpoint_ref` projection only when a matching
  checkpoint is actually persisted;
- external report-key omission and management-surface denial;
- checkpoint fingerprint validation before current `RuntimePolicyGate` recheck;
- mismatch-visible `CHECKPOINT_MISMATCH` before paused-shell policy denial;
- matching paused resumes still fail closed with `DENY_PAUSED`;
- safe resume `output_ref` and safe RunTrace checkpoint-resume append;
- typed OpenAPI error contracts for `404`, `409`, `500`, and `503`;
- typed `CHECKPOINT_READ_FAILED` for checkpoint backend read failures in both
  the HTTP route and `AgentRuntime.resume_from_checkpoint(...)`.

This verification does not authorize merge, push, release, independent-review
substitution, workflow replacement, wall-clock preemption, automatic R4/R5
execution, or any autonomous-core evidence claim.

## Fresh Targeted Verification

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3 -m unittest -q tests.unit.test_agent_runtime_replay_boundary tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_run_response_carries_runtime_checkpoint_ref tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_run_response_omits_runtime_checkpoint_ref_without_checkpoint_store tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_replays_checkpoint_without_rerunning_trusted_loop tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_mismatch_fails_closed_without_raw_args tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_context_mismatch_does_not_echo_untrusted_trace_id tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_without_checkpoint_store_is_service_unavailable tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_checkpoint_read_failure_is_typed_500 tests.unit.test_http_app.HttpAppAuthBoundaryTest.test_api_principal_scope_contract_is_explicit tests.unit.test_http_app.HttpAppAuthBoundaryTest.test_external_report_key_cannot_use_management_surfaces tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema tests.unit.test_openapi_contract.OpenApiContractTest.test_contract_covers_all_trigger_surfaces tests.unit.test_openapi_contract.OpenApiContractTest.test_agent_runtime_resume_contract_is_declared
```

Observed on 2026-07-01:

- targeted public-resume suite: 23 tests OK;
- expected Starlette/httpx deprecation warning only.

## Fresh Full Verification

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Observed on 2026-07-01:

- ruff clean;
- formatting clean (`114 files already formatted`);
- primary unittest discovery: 505 tests OK, 4 skipped;
- eval suite: 12 tests OK;
- OpenAPI snapshot up to date;
- `=== All CI checks passed ===`.

```bash
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Observed on 2026-07-01:

- ruff clean;
- formatting clean (`114 files already formatted`);
- primary unittest discovery: 505 tests OK, 4 skipped;
- eval suite: 12 tests OK;
- OpenAPI snapshot up to date;
- `=== Full local CI parity checks passed ===`.

## Boundary

The branch remains local. Before any deployment local-main merge, require
explicit founder/CTO authorization and re-run the fast-forward check immediately
before merging. If founder/CTO requires independent review, obtain it before
merge. Push and external release remain separate gates.
