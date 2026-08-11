# ADR-0003 Agent Runtime Success Trace Bridge Review

- Date: 2026-06-26
- Branch reviewed: `codex/agent-runtime-success-trace-bridge-current`
- Base: local `main` at `3249c36`
- Reviewed head: `ee2a9fb`
- Scope: successful `POST /runs` Agent Runtime envelope event persistence into queryable `RunTrace`
- Status: approved for founder/CTO fast-forward decision, subject to merge-order constraint below

## Verdict

**APPROVED FOR FOUNDER/CTO FF DECISION.**

No merge-blocking finding was found for this slice. The implementation preserves the existing Trusted Loop answer/action path and only bridges safe runtime-envelope metadata into the persisted business trace after a successful `TrustedLoopRuntime.evaluate()` result has produced a trace id.

This approval is scoped: it covers successful `/runs` runtime-envelope trace persistence only. It does not approve `/approvals/{approval_id}/execute` runtime-envelope migration, production telemetry export, workflow replacement, automatic R4/R5 execution, or external release.

## Review Checks

### Runtime boundary

`run_service(...)` still obtains the trusted result from the existing runtime output before any success-trace bridge is attempted. The bridge runs after `outcome.result` and `result.evidence_chain.trace_id` exist, then fetches the already persisted business trace and replaces only its `events` tuple with runtime-envelope events inserted around the existing Trusted Loop events.

Relevant code:

- `apps/api_server/src/agent_os_api/outcome_service.py:92`
- `apps/api_server/src/agent_os_api/outcome_service.py:624`

### Trace payload safety

Persisted Agent Runtime event payloads are allowlisted to:

- `call_id`
- `tool_name`
- `run_id`
- `status`
- `error_code`

The bridge does not persist raw request parameters, raw tool output, SQL, parameter values, connector payloads, or exception strings. The regression test checks that the request window fields and sample parameter value do not appear in persisted runtime payloads.

Relevant test:

- `tests/unit/test_http_app.py:64`

### Authorization surface

The persisted events become visible through `/traces/{trace_id}` only. That route still requires `traces:read`, and `external_report` principals do not carry that scope.

Relevant code:

- `apps/api_server/src/agent_os_api/http_app.py:73`
- `apps/api_server/src/agent_os_api/http_app.py:87`
- `apps/api_server/src/agent_os_api/http_app.py:810`

### Event ordering

The test asserts that `agent_runtime.tool_started` precedes the business `intent` event and that `agent_runtime.tool_succeeded` follows `knowledge_asset_candidate`. That keeps the audit interpretation clear: the runtime envelope surrounds the Trusted Loop rather than replacing it.

Relevant test:

- `tests/unit/test_http_app.py:83`

### Risk and approval boundary

No R4/R5 policy path, approval execution path, connector execution path, SQL Safety path, EvidenceChain path, or `TrustedLoopRuntime` core behavior is changed in this diff.

## Merge-Order Constraint

There is a parallel branch, `codex/agent-runtime-approval-execute-envelope`, forked from the same local `main`. This success-trace branch can fast-forward into current local `main` as-is. However, the two branches touch overlapping files including:

- `README.md`
- `docs/CURRENT_STATE.yaml`
- `docs/decisions/ADR-0003-agent-runtime-v0-trusted-substrate.md`
- `docs/decisions/ADR-0003-agent-runtime-v0-trusted-substrate.SPEC.md`
- `docs/decisions/README.md`
- `apps/api_server/src/agent_os_api/outcome_service.py`
- `tests/unit/test_http_app.py`

Therefore:

- if success-trace merges first, `codex/agent-runtime-approval-execute-envelope` must be rebased/re-reviewed before merge;
- if approval-execute merges first, this success-trace branch must be rebased/re-reviewed before merge;
- do not attempt to merge both branches without resolving the overlap.

## Verification Reviewed

Branch-local implementation verification recorded in `ADR-0003-agent-runtime-success-trace-bridge.IMPLEMENTATION-20260626.md`:

```text
Red test: 'agent_runtime.policy_allowed' not found in persisted trace.
Focused success-trace test after implementation: ok.
Affected HTTP/service/adapter suite: 62 tests OK.
make ci: ruff clean; format clean; 454 tests OK; 4 skipped; 12 eval tests OK; OpenAPI contract drift check passed.
ci-local-full: full local CI parity checks passed against PostgreSQL on 127.0.0.1:5432/agent_os_test.
```

Additional review checks run:

```text
git diff --check main...HEAD
git diff --name-status main...HEAD
git merge-tree <merge-base> codex/agent-runtime-success-trace-bridge-current codex/agent-runtime-approval-execute-envelope
```

Result:

- whitespace check clean;
- reviewed changed file set matches the implementation scope;
- merge-tree confirms branch overlap with the parallel approval-execute runtime branch.

## Gate Result

Founder/CTO may fast-forward local `main` to `codex/agent-runtime-success-trace-bridge-current` if this slice is chosen next. Do not push or merge without explicit authorization.
