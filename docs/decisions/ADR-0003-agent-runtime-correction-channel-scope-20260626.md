# ADR-0003 Scope: Agent Runtime Correction Channel

Date: 2026-06-26
Status: SCOPE CANDIDATE ONLY - NOT IMPLEMENTED
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

Do not implement this slice on top of an unmerged stacked branch unless explicitly
approved. Preferred sequence:

1. Fast-forward the reviewed ADR-0003 stack into local `main` after explicit
   founder/CTO authorization.
2. Run post-merge `make ci` and `ci-local-full` on `main`.
3. Open a fresh branch from updated `main` for the correction-channel runtime
   envelope.
4. Write the failure-first tests above before implementation.
