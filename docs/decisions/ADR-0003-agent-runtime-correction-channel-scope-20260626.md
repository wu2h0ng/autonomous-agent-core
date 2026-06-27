# ADR-0003 Scope: Agent Runtime Correction Channel

Date: 2026-06-26
Status: IMPLEMENTED AND SELF-REVIEWED LOCALLY ON `codex/agent-runtime-correction-channel` - FOUNDER/CTO MERGE AUTHORIZATION PENDING
Depends on: stacked merge of `codex/agent-runtime-reviewed-slices-consolidation`,
`codex/agent-runtime-checkpoint-factory-selection`, and
`codex/agent-runtime-budget-guard` into local `main`

## Purpose

The next narrow runtime slice should cover the correction/value-feedback channel
without weakening the P5.1b anti-wirehead boundary.

Existing product semantics:

- `POST /outcomes` is runtime self-report. It records feedback but does not
  promote knowledge.
- `POST /adoptions` is the operator/external value channel. It records realized
  adoption and may promote the trace's `KnowledgeAsset`.
- `TrustedLoopRuntime` holds only the read view of adoption value. The
  composition/operator layer holds the adoption writer.

The correction-channel runtime slice should prove that these correction inputs
can traverse an Agent Runtime envelope for policy/trace/audit purposes while
keeping the existing value authority intact.

## Non-Negotiable Boundary

Agent Runtime must not become the value authority.

Do not give `AgentRuntime`, `TrustedLoopRuntime`, or a self-report tool an
`AdoptionIngest` writer. The operator/composition surface remains the only owner
of realized external-value writes.

## Proposed Narrow Architecture

```text
POST /outcomes
  -> ApiPrincipal(scope=outcomes:write)
  -> AgentRunContext(surface=POST /outcomes, risk_ceiling=R1)
  -> TrustedLoopCorrectionRuntimeAdapter.record_outcome()
  -> RuntimePolicyGate.check()
  -> AgentRuntime.invoke_tool()
  -> record_outcome_service()
  -> TrustedLoopRuntime.record_outcome()
  -> FeedbackStore
  -> no KnowledgeAsset promotion

POST /adoptions
  -> ApiPrincipal(scope=adoptions:write)
  -> AgentRunContext(surface=POST /adoptions, risk_ceiling=R2)
  -> TrustedLoopCorrectionRuntimeAdapter.attest_adoption()
  -> RuntimePolicyGate.check()
  -> AgentRuntime.invoke_tool()
  -> attest_adoption_service(runtime, adoption_ingest)
  -> AdoptionIngest.submit()
  -> TrustedLoopRuntime.promote_from_adoption()
  -> KnowledgeAsset revision if trace has a candidate
```

The adapter may live beside the existing Trusted Loop runtime adapters, but it
must remain a thin composition wrapper. It must not encode product scoring,
knowledge-promotion policy, or business task strategy.

## Tool Specs

Candidate runtime tools:

```text
trusted_loop.record_outcome
  risk_level: R1
  side_effect_class: self_report_feedback
  required_permissions: trusted_loop:record_outcome
  requires_approval: false

trusted_loop.attest_adoption
  risk_level: R2
  side_effect_class: external_value_attestation
  required_permissions: trusted_loop:attest_adoption
  requires_approval: false
```

Because the current `RuntimePolicyGate` treats non-read side effects as
approval-required by default, this slice must explicitly decide one of two safe
options before implementation:

1. Add an allowlisted "correction_channel" side-effect class family that is
   permitted without `approval_id` only for scoped principals and only below R3.
2. Keep the tool specs as `requires_approval=True` and require an explicit
   correction approval context before external adoption can write value.

Recommended v0 decision: option 1 for `record_outcome`, and option 2 or a new
operator-key-only correction approval for `attest_adoption`. The external value
writer is more sensitive than self-report feedback.

## Implementation Decision (2026-06-27)

The local implementation uses a narrow version of option 1 for both tools:

- `RuntimePolicyGate` allowlists only the correction-channel side-effect classes
  `self_report_feedback` and `external_value_attestation`.
- The allowlist applies only when the tool risk is below R3 and the tool declares
  required permissions. Missing `trusted_loop:record_outcome` or
  `trusted_loop:attest_adoption` still denies before the tool body.
- Arbitrary non-read side effects remain approval-required by default, and
  R4/R5 execution remains proposal-only.
- `TrustedLoopCorrectionRuntimeAdapter` lives in the API/service composition
  layer. It may receive the operator-held `AdoptionIngest` for the adoption tool,
  but neither `AgentRuntime` nor `TrustedLoopRuntime` receives an adoption writer.
- `POST /outcomes` and `POST /adoptions` each create a request-scoped
  `AgentRunContext`, `AgentTraceWriter`, and correction adapter before invoking
  existing service functions.
- Runtime trace persistence keeps only the allowlisted
  `call_id/tool_name/run_id/status/error_code` metadata and excludes raw metric
  deltas, causal-attribution payloads, secret-like keys, contract objects, and
  full business payloads.
- The HTTP correction routes inject the request checkpoint store into their
  side-effecting correction adapters. The two correction tools set
  `ToolSpec.preserve_result_on_checkpoint_failure=True` so a completed
  feedback/adoption write is not converted into a retry-inducing HTTP failure if
  the checkpoint backend fails after the write. The default runtime behavior for
  other tools remains `checkpoint_error`, and the correction path still emits
  safe `agent_runtime.checkpoint_failed` evidence.

This keeps current API authorization semantics (`adoptions:write` is still the
realized-value HTTP scope) while adding a second runtime permission/pause gate.
It does not add operator-key-only correction approval; that remains a possible
future hardening slice if the external value channel is promoted above the
current internal API surface.

## Verification (2026-06-27)

- Failure-first targeted tests were added in
  `tests/unit/test_agent_runtime_correction_channel.py` and
  `tests/unit/test_http_app.py`.
- Failure-first coverage targets the pre-existing bypass shape: `/outcomes` and
  `/adoptions` must enter through request-scoped runtime context, deny before
  feedback/adoption writes when paused or missing permissions, and preserve
  writer authority. During hardening, `test_outcome_runtime_denial_preserves_existing_run_trace`
  first failed because terminal correction denial overwrote the prior `/runs`
  trace instead of appending safe denial events.
- Branch-local review found a post-write ambiguity: a failing checkpoint store
  could make `/adoptions` return `409 checkpoint save failed` after the external
  adoption write had already completed, inviting duplicate retry. The red test
  `test_adoptions_preserve_success_on_checkpoint_failure_after_value_write`
  failed on that behavior before `ToolSpec.preserve_result_on_checkpoint_failure`
  was added and enabled only for the correction tools.
- GREEN evidence after implementation:
  - targeted runtime/correction suite covering correction-channel, policy,
    tool, replay-boundary, outcome-service, and HTTP paths: 102 tests OK;
  - `make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python`:
    ruff clean, format clean, 494 unittest tests OK with 4 skipped, 12 eval
    tests OK, OpenAPI drift check passed;
  - `AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python`:
    full local CI parity passed with the same 494 tests OK / 4 skipped, 12 eval
    tests OK, and OpenAPI up to date.

## Required Failure-First Tests

Add tests before implementation:

- `POST /outcomes` traverses the runtime envelope and still does not promote
  knowledge.
- Paused shell denies `POST /outcomes` before `TrustedLoopRuntime.record_outcome`
  and before feedback write.
- `POST /adoptions` traverses the runtime envelope and preserves the existing
  adoption writer authority.
- Paused shell denies `POST /adoptions` before `AdoptionIngest.submit`.
- Missing `trusted_loop:record_outcome` or `trusted_loop:attest_adoption`
  permission denies before the service call.
- Runtime trace events for both routes are request-scoped and safe: no raw
  metric deltas, causal-attribution payload, secret-like keys, raw contract
  object, or full business payload.
- Checkpoint backend failure after a completed adoption write does not turn the
  HTTP response into a retry-inducing failure, but remains trace-visible.
- Self-report feedback cannot be replayed as external adoption through a runtime
  checkpoint.
- External adoption cannot be executed through `record_outcome`.
- Unknown trace still records correction according to existing service semantics
  but does not fabricate a knowledge asset.

## Acceptance Criteria

- `/outcomes` and `/adoptions` have real runtime-envelope entry paths.
- Existing P5.1b semantics remain true:
  - self-report never promotes knowledge;
  - external adoption is the only realized-value promotion path;
  - runtime owns no adoption writer.
- Trace evidence can prove whether correction was allowed, denied, failed, or
  completed without exposing raw payloads.
- Paused shell blocks both correction channels before writes.
- R4/R5 business action execution remains unrelated and fail-closed.
- No external agent framework dependency is introduced.
- No autonomous-core claim is made.

## Stop Conditions

Stop and return to CTO/founder review if:

- implementing the slice requires `AgentRuntime` or `TrustedLoopRuntime` to hold
  an adoption writer;
- the runtime policy gate must broadly permit arbitrary non-read side effects;
- adoption promotion starts depending on runtime self-report;
- checkpoint replay can replay external adoption without the same correction
  authority context;
- trace persistence requires raw metric deltas, causal-attribution details, or
  full feedback/adoption payloads.

## Next Gate

The implementation is on a fresh branch from updated `main` and has local
verification plus a branch-local self-review record:

- `ADR-0003-agent-runtime-correction-channel.REVIEW-20260627.md`

Remaining gate:

1. Obtain explicit founder/CTO authorization before merging
   `codex/agent-runtime-correction-channel` into local `main`.
2. Run post-merge `make ci` and `ci-local-full` on local `main`.
3. Do not push, release, or claim external shipment unless a later release gate
   explicitly authorizes it.
