# ADR-0003 Self-Review: Agent Runtime Public Resume API

Date: 2026-06-27
Status: BRANCH-LOCAL SELF-REVIEW COMPLETE - NOT INDEPENDENT REVIEW / NOT MERGE AUTHORIZATION
Branch: `codex/agent-runtime-public-resume-api`
Reviewed implementation commit: `2a3150f`
Base: `main@69389a5`
Reviewed implementation range: `main@69389a5..2a3150f`

## Scope

This self-review covers the branch-local public resume API slice:

- `POST /runs` internal-only `runtime_checkpoint_ref` projection;
- `POST /agent-runtime/runs/{runtime_run_id}/resume`;
- `runtime:resume` HTTP principal/scope contract;
- `AgentRuntime.resume_from_checkpoint` policy recheck before checkpoint return;
- checkpoint mismatch, missing checkpoint, missing store, and paused-shell failures;
- safe output projection, safe trace append, OpenAPI snapshot, tests, and docs.

This is a Codex self-review. Claude Code independent diff review was attempted
twice from this worktree, but both non-interactive runs stalled with no review
output and were terminated. Therefore this record must not be treated as
independent approval or founder/CTO merge authorization.

## Findings

No blocking findings remain after in-review remediation.

One recoverability issue was found and fixed before this self-review was
finalized:

- `POST /runs` returned a `runtime_checkpoint_ref` even when no checkpoint store
  was configured, creating a non-recoverable resume reference. This was fixed in
  `9b98286` by projecting `runtime_checkpoint_ref` only when the checkpoint
  store can prove a matching persisted checkpoint exists. The regression test is
  `test_run_response_omits_runtime_checkpoint_ref_without_checkpoint_store`.

Reviewed security and authority properties:

- `external_report` does not receive `runtime:resume`; only the internal API
  principal has that scope.
- External report-key `POST /runs` projections force `runtime_checkpoint_ref =
  null`.
- `POST /runs` only emits `runtime_checkpoint_ref` when a matching checkpoint
  exists, has a stored result, matches the runtime trace id, and names the
  expected `trusted_loop.evaluate` tool.
- Resume prevalidates the checkpoint store, run snapshot, and supplied
  `runtime_trace_id` before constructing a runtime context, so an untrusted
  caller-supplied trace id is not echoed into HTTP errors or runtime trace
  events on mismatch.
- Resume reconstructs the original `trusted_loop.evaluate` tool call and
  delegates to `AgentRuntime.resume_from_checkpoint`; it does not call the
  Trusted Loop body directly.
- `AgentRuntime.resume_from_checkpoint` rechecks `RuntimePolicyGate` before
  reading and returning checkpoint data, so a paused shell denies resume before
  checkpoint return.
- Fingerprint mismatch fails closed without tool execution and without raw arg
  echo.
- Successful resume returns only `RuntimeResumeResponse.output_ref`, not raw
  tool output, raw SQL, original parameters, or connector payloads.
- Successful resume appends only safe `agent_runtime.checkpoint_resume_*`
  events to the business `RunTrace`.

## Open Questions

- Should a later independent reviewer require operator-key or a distinct
  runtime-management key for resume, instead of the current internal API key
  plus `runtime:resume` scope?

This question does not block the current branch-local implementation, but it is
a reasonable future hardening candidate before external release.

## Required Changes

Required change completed in `9b98286`:

- add the persisted-checkpoint projection guard for `runtime_checkpoint_ref`;
- add the negative test for no-checkpoint-store `/runs` behavior;
- sync implementation log, gap audit, README, and `CURRENT_STATE.yaml`.

Required change completed after initial self-review in `2a3150f`:

- declare typed `RuntimeResumeErrorResponse` OpenAPI schemas for `404`, `409`,
  `500`, and `503` resume failures;
- extend `test_agent_runtime_resume_contract_is_declared` to prove the
  non-200 error contract.

## Evidence

Implementation log:

- `docs/decisions/ADR-0003-agent-runtime-public-resume-api.IMPLEMENTATION-20260627.md`

Primary reviewed files:

- `apps/api_server/src/agent_os_api/http_app.py`
- `packages/os_core/src/agent_os_core/agent_runtime/__init__.py`
- `tests/unit/test_http_app.py`
- `tests/unit/test_agent_runtime_replay_boundary.py`
- `tests/unit/test_openapi_contract.py`
- `apps/api_server/openapi.json`

Verification recorded after reviewed implementation and readiness docs:

```text
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result: ruff clean, format clean, `502` primary unittest tests OK with `4`
skipped, `12` eval tests OK, OpenAPI drift check passed.

```text
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result: full local CI parity passed with `502` primary unittest tests OK, `12`
eval tests OK, and OpenAPI up to date.

Failure-first coverage that would fail on bypass:

- no checkpoint store returns no `runtime_checkpoint_ref` on `POST /runs` and
  `503 CHECKPOINT_NOT_AVAILABLE` on resume;
- external report key cannot use the resume route;
- paused shell denies resume before returning checkpoint data;
- changed args produce `CHECKPOINT_MISMATCH` without raw arg echo or tool
  execution;
- mismatched caller-supplied `runtime_trace_id` does not appear in the HTTP
  response or runtime trace events;
- successful resume appends safe checkpoint resume events without
  `agent_runtime.tool_started`;
- OpenAPI declares the resume path, request, response, and safe `output_ref`
  schema.

## Engineering Reality Gate

Entry point:

- `POST /runs`
- `POST /agent-runtime/runs/{runtime_run_id}/resume`

Contract:

- `RuntimeCheckpointRef`
- `RuntimeResumeRequest`
- `RuntimeResumeResponse`
- `RuntimeResumeOutputRef`
- `AgentRunContext`
- `AgentToolCall`
- `AgentToolResult`

Failure mode:

- Missing checkpoint store returns `503 CHECKPOINT_NOT_AVAILABLE`.
- Missing checkpoint returns `404 CHECKPOINT_NOT_FOUND`.
- Runtime trace mismatch returns `409 CHECKPOINT_MISMATCH` before runtime
  context construction.
- Call/context/tool fingerprint mismatch returns `409 CHECKPOINT_MISMATCH`
  through the runtime boundary.
- Paused shell and missing runtime permissions deny before checkpoint return.

Test validity:

- The tests would fail if external report keys could use resume, if
  `runtime_checkpoint_ref` were exposed without a persisted checkpoint, if
  resume reran `TrustedLoopRuntime.evaluate`, if raw args leaked, if an
  untrusted trace id were echoed, or if `RuntimePolicyGate` were skipped before
  checkpoint return.

Integration:

- The slice uses the existing `TrustedLoopAgentRuntimeAdapter`, factory-selected
  checkpoint store, `RunTrace` persistence, and HTTP auth scope matrix.

Boundary:

- No external agent framework dependency is introduced.
- No cross-repo import is introduced.
- No autonomous-core result is claimed.
- No R4/R5 automatic execution is introduced.
- The route is not merged, pushed, released, or externally shipped.

Observability:

- Resume success/failure is represented through safe `agent_runtime.*` trace
  events, and successful resume appends safe events to the existing business
  trace when a business trace id is available.

Product/process boundary:

- This is product runtime recoverability behavior in the deployment layer. It
  is not meta-layer workflow automation and not proof of autonomy, RSI, AGI, or
  complete Agent OS productization.

## Residual Risks

- This is self-review only. A separate independent review or explicit
  founder/CTO judgment is still required before local-main merge.
- The route is internal-only but still management-like; a later hardening slice
  may choose a distinct runtime-management credential boundary.
- This does not implement wall-clock interruption, streaming cancellation,
  workflow concurrency semantics, production telemetry export, or external
  release readiness.

## Gate Outcome

Outcome: SELF-REVIEW ACCEPTABLE FOR FOUNDER/CTO MERGE DECISION; NOT MERGE AUTHORIZATION.

Merge readiness is recorded in
`ADR-0003-agent-runtime-public-resume-api.MERGE-READINESS-20260627.md`.

Do not merge, push, release, or describe this branch as externally shipped
without explicit founder/CTO authorization and the required post-merge
verification gate.
