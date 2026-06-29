# ADR-0003 Public Resume API Refresh Verify

Date: 2026-06-29
Status: BRANCH-LOCAL REFRESH VERIFIED - NOT MERGED/PUSHED/RELEASED
Repo: `ai-native-business-data-agent-os`
Branch: `codex/agent-runtime-public-resume-api`
Runtime/source head verified: `7fd08f1 docs(runtime): record public resume post verification`

## Scope

Refresh verification after rebasing the branch onto deployment local `main@8556efc`.
This record covers the same branch-local Agent Runtime public resume API slice:

- internal-only `POST /agent-runtime/runs/{runtime_run_id}/resume`
- `runtime:resume` scope on the internal API principal only
- persisted-checkpoint `runtime_checkpoint_ref` projection from `POST /runs`
- external-report-key omission and management-surface denial
- `RuntimePolicyGate` pause/policy recheck before checkpoint return
- fingerprint mismatch fail-closed behavior without Trusted Loop re-execution
- safe resume `output_ref` and safe RunTrace checkpoint-resume append
- typed OpenAPI error contracts for `404`, `409`, `500`, and `503`

This is a docs-only refresh record. It does not authorize merge, push, release,
independent-review substitution, workflow replacement, wall-clock preemption,
automatic R4/R5 execution, or an autonomy claim.

## Targeted Verification

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src \
/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest -q \
  tests.unit.test_agent_runtime_replay_boundary.AgentRuntimeReplayBoundaryTest.test_resume_respects_paused_shell_before_returning_checkpoint \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_internal_run_response_carries_runtime_checkpoint_ref \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_run_response_omits_runtime_checkpoint_ref_without_checkpoint_store \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_replays_checkpoint_without_rerunning_trusted_loop \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_mismatch_fails_closed_without_raw_args \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_context_mismatch_does_not_echo_untrusted_trace_id \
  tests.unit.test_http_app.HttpAppSharedRuntimeTest.test_runtime_resume_without_checkpoint_store_is_service_unavailable \
  tests.unit.test_http_app.HttpAppAuthBoundaryTest.test_api_principal_scope_contract_is_explicit \
  tests.unit.test_http_app.HttpAppAuthBoundaryTest.test_external_report_key_cannot_use_management_surfaces \
  tests.unit.test_openapi_contract.OpenApiContractTest.test_snapshot_matches_live_schema \
  tests.unit.test_openapi_contract.OpenApiContractTest.test_contract_covers_all_trigger_surfaces \
  tests.unit.test_openapi_contract.OpenApiContractTest.test_agent_runtime_resume_contract_is_declared
```

Observed on 2026-06-29:

- `12` targeted tests OK
- expected Starlette/httpx deprecation warning only

## Full Verification

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Observed on 2026-06-29:

- ruff clean
- formatting clean (`114 files already formatted`)
- primary unittest discovery: `502` tests OK, `4` skipped
- eval suite: `12` tests OK
- OpenAPI snapshot up to date
- `=== All CI checks passed ===`

```bash
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Observed on 2026-06-29:

- ruff clean
- formatting clean (`114 files already formatted`)
- primary unittest discovery: `502` tests OK, `4` skipped
- eval suite: `12` tests OK
- OpenAPI snapshot up to date
- `=== Full local CI parity checks passed ===`

## Merge Boundary

The branch remains local after refresh verification. Before any deployment
local-main merge, require explicit founder/CTO authorization and re-run the
fast-forward check immediately before merging. If founder/CTO requires
independent review, obtain it before merge. Push and external release remain
separate gates.
