# ADR-0003 Review: Agent Runtime v0 Trusted Substrate

- Review date: 2026-06-24
- Branch reviewed: `codex/agent-runtime-v0-trusted-substrate`
- Reviewed commit: `58f3a5f`
- Base: enterprise `main` `ad87efa`
- Scope: merge-readiness review for ADR-0003 before merging to `main`
- Approval status: **NOT APPROVED FOR MERGE**

## Findings

### H1 - `run_tool()` bypasses the runtime policy gate

- Severity: HIGH / merge blocker
- File: `packages/os_core/src/agent_os_core/agent_runtime/__init__.py:260`
- Spec conflict: `docs/decisions/ADR-0003-agent-runtime-v0-trusted-substrate.SPEC.md:185`

`AgentRuntime.run_tool()` still calls `self.tools.call(...)` directly, bypassing context validation, pause checks, permission checks, approval checks, structured deny results, trace events, and checkpointing. This conflicts with the ADR-0003 requirement that the runtime gate runs before `ToolRegistry.call`.

Local reproduction:

```text
direct_run_tool_result= {'ok': True} called= ['ran']
```

The reproduced tool required `admin:write` and `requires_approval=True`, while the context had neither permission nor `approval_id`. It still executed through `run_tool()`.

Required change:

- Route `run_tool()` through `invoke_tool()` with a compatibility-generated `AgentToolCall`, or remove/export-hide the bypassing method and make old callers migrate.
- Add a regression test proving `run_tool()` cannot bypass permission, approval, pause, trace, and validation gates.

### H2 - R4/R5 and side-effect metadata are decorative, not enforced

- Severity: HIGH / merge blocker
- File: `packages/os_core/src/agent_os_core/agent_runtime/__init__.py:175`
- File: `packages/os_core/src/agent_os_core/agent_runtime/__init__.py:217`
- Spec conflict: `docs/decisions/ADR-0003-agent-runtime-v0-trusted-substrate.SPEC.md:33`
- Spec conflict: `docs/decisions/ADR-0003-agent-runtime-v0-trusted-substrate.SPEC.md:168`

`RuntimePolicyGate` accepts `R0` through `R5` by default and only checks whether a risk level is in that supported set. It does not impose an R4/R5 proposal-only rule, does not require approval/evidence for side-effecting tools, and does not use `side_effect_class` except as metadata. A tool registered as `risk_level="R5"` and `side_effect_class="external_write"` executes if `requires_approval` is omitted.

Local reproduction:

```text
r5_invoke_status= ok error= None called= ['ran']
```

Required change:

- Add a default risk ceiling or explicit `max_executable_risk_level`, with R4/R5 denied or approval/proposal-bound by default.
- Enforce `side_effect_class != "none"` and/or `risk_level in {"R4","R5"}` through policy, not only through caller discipline.
- Add regression tests proving R4/R5 and external-write tools cannot execute automatically.

### H3 - Trace events log raw args and outputs by default

- Severity: HIGH / merge blocker
- File: `packages/os_core/src/agent_os_core/agent_runtime/__init__.py:265`
- File: `packages/os_core/src/agent_os_core/agent_runtime/__init__.py:382`
- File: `packages/os_core/src/agent_os_core/agent_runtime/__init__.py:415`
- Spec conflict: `docs/decisions/ADR-0003-agent-runtime-v0-trusted-substrate.SPEC.md:231`

The runtime writes full `call.args` on `invocation_started` and `tool_started`, then writes full `output` on `tool_succeeded`. Redaction is optional and only works when the caller passes `AgentTraceWriter(sensitive_keys=...)`. With the default trace writer, secret-like fields and sensitive business payloads are recorded verbatim.

Local reproduction:

```text
True
agent_runtime.invocation_started {'call_id': 'c', 'tool_name': 'secret.echo', 'run_id': 'r', 'trace_id': 'tr', 'args': {'api_key': 'sk-live'}}
agent_runtime.tool_started {'call_id': 'c', 'tool_name': 'secret.echo', 'args': {'api_key': 'sk-live'}}
agent_runtime.tool_succeeded {'call_id': 'c', 'tool_name': 'secret.echo', 'output': {'api_key': 'sk-live'}}
```

Required change:

- Do not trace raw args/output by default. Prefer argument key lists, stable fingerprints, schema IDs, row counts, or an explicit allowlist.
- If redaction remains configurable, provide a safe default denylist and a `ToolSpec`-level trace projection policy.
- Add regression tests proving default tracing does not leak secret-like fields.

### M1 - Trusted Loop adapter test does not exercise the real TrustedLoopRuntime

- Severity: MEDIUM / should fix before merge unless explicitly accepted as a smoke-only test
- File: `tests/integration/test_trusted_loop_agent_runtime_adapter.py:22`
- Spec reference: `docs/decisions/ADR-0003-agent-runtime-v0-trusted-substrate.SPEC.md:262`

The adapter test uses `FakeTrustedLoop`, so it proves only that a fake object's `evaluate()` method is called through `invoke_tool()`. It does not prove the adapter preserves real `TrustedLoopRuntime.evaluate()` behavior, SQL Safety, EvidenceChain, or `TrustedLoopOutcome` shape.

Required change:

- Add one real minimal `TrustedLoopRuntime` adapter test that executes the existing safe path and asserts the returned outcome still carries the expected Trusted Loop result/evidence behavior.
- Keep the fake test if useful for pause-before-call isolation.

### M2 - Checkpoint failures are not represented as structured runtime failures

- Severity: MEDIUM / follow-up acceptable if H1-H3 are fixed and scoped explicitly
- File: `packages/os_core/src/agent_os_core/agent_runtime/__init__.py:425`
- Spec reference: `docs/decisions/ADR-0003-agent-runtime-v0-trusted-substrate.SPEC.md:88`

`_checkpoint()` runs after tool execution and can raise out of `invoke_tool()` if the checkpoint store fails. That means a successful tool execution may surface as an unstructured runtime exception after side effects have already happened, with no `AgentToolResult` or trace event for checkpoint failure.

Required change:

- Either catch checkpoint failures and return/trace a structured `checkpoint_error`, or explicitly mark checkpoint failure handling as out of scope for v0 and avoid wiring non-in-memory checkpoint stores before ADR-0004.

## Open Questions

- Should `run_tool()` remain part of the public compatibility API, or should this review force all callers onto `invoke_tool()` before merge?
- Should the v0 runtime have a hard default risk ceiling of R3, or should R4/R5 be allowed only when a separate proposal/approval binding object is present?
- What is the approved trace projection policy for product runtime tools: deny raw payloads entirely, default denylist, or tool-specific allowlist?

## Required Changes

1. Close H1: remove or gate the `run_tool()` bypass.
2. Close H2: enforce risk/side-effect policy in `RuntimePolicyGate`.
3. Close H3: make trace projection safe by default.
4. Add tests covering each closed blocker.
5. Re-run `make ci` and `ci-local-full`.
6. Update `docs/CURRENT_STATE.yaml` and this review trail after remediation.

## Approval Status

ADR-0003 is **not approved for merge** at commit `58f3a5f`.

The branch is a good substrate direction, but H1-H3 are exactly the kind of governance drift this review gate is meant to catch: compatibility bypass, metadata-only risk policy, and trace leakage. Merge should wait for remediation and a second review pass.
