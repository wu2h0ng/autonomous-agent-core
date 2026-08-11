# ADR-0003 Review: Agent Runtime Correction Channel

Date: 2026-06-27
Status: BRANCH-LOCAL SELF-REVIEW COMPLETE; LOCAL MAIN MERGE AUTHORIZED AND COMPLETED - NO PUSH/RELEASE CLAIM
Branch: `codex/agent-runtime-correction-channel`
Base: `main@dba87bc`
Reviewed range: `main@dba87bc..codex/agent-runtime-correction-channel`

## Scope

This review covered the branch-local correction-channel runtime envelope for:

- `POST /outcomes`
- `POST /adoptions`
- `TrustedLoopCorrectionRuntimeAdapter`
- the narrow `RuntimePolicyGate` correction side-effect allowlist
- correction-channel tests and documentation updates

This review is not an external independent review and not a release claim. It
was used as a branch-local gate record before the founder/CTO-authorized local
fast-forward merge to deployment `main`.

## Reviewed Diff

Primary implementation files:

- `packages/os_core/src/agent_os_core/agent_runtime/__init__.py`
- `apps/api_server/src/agent_os_api/outcome_service.py`
- `apps/api_server/src/agent_os_api/http_app.py`

Primary tests:

- `tests/unit/test_agent_runtime_correction_channel.py`
- `tests/unit/test_http_app.py`

Synchronized docs:

- `README.md`
- `docs/CURRENT_STATE.yaml`
- `docs/decisions/ADR-0003-agent-runtime-v0-trusted-substrate.SPEC.md`
- `docs/decisions/ADR-0003-agent-runtime-correction-channel-scope-20260626.md`
- `docs/decisions/ADR-0003-agent-runtime-capability-gap-audit-20260626.md`

## Decision

Branch-local self-review found one blocking post-write ambiguity and the branch
was remediated before merge decision:

- finding: `/adoptions` can complete `AdoptionIngest.submit()` before the
  runtime checkpoint write; returning `409 checkpoint save failed` after that
  point would invite a duplicate-value retry;
- fix: HTTP correction routes now inject the factory-selected checkpoint store,
  while the two correction tools explicitly set
  `ToolSpec.preserve_result_on_checkpoint_failure=True`; default runtime tools
  still return `checkpoint_error` on checkpoint save failure;
- regression: `test_adoptions_preserve_success_on_checkpoint_failure_after_value_write`
  and `test_checkpoint_failure_can_preserve_result_for_irreversible_side_effects`
  failed before the fix and now pass.

The implementation preserves the intended authority split:

- `/outcomes` remains self-report feedback and does not promote knowledge.
- `/adoptions` remains the realized external-value channel and promotes
  knowledge only through the existing adoption writer.
- `AgentRuntime` and `TrustedLoopRuntime` do not hold an adoption writer.
- The adoption writer is held only by the API/service composition adapter.

The runtime policy change is intentionally narrow:

- only `self_report_feedback` and `external_value_attestation` side-effect
  classes are exempted from the generic approval requirement;
- the exemption only applies at risk `R2` or below;
- the tool must declare required permissions;
- missing runtime permissions deny before tool execution;
- arbitrary non-read side effects still require approval;
- R4/R5 non-proposal execution remains denied before the tool body.

## Evidence

Current branch verification:

```text
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result: ruff clean, format clean, 494 unittest tests OK with 4 skipped, 12 eval
tests OK, OpenAPI drift check passed.

```text
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result: full local CI parity passed with the same 494 tests OK / 4 skipped, 12
eval tests OK, and OpenAPI up to date.

Failure-first coverage that would fail on bypass:

- Missing `trusted_loop:record_outcome` denies before feedback write.
- Missing `trusted_loop:attest_adoption` denies before adoption write.
- Paused shell denies `/outcomes` before feedback write.
- Paused shell denies `/adoptions` before adoption write.
- HTTP `/outcomes` and `/adoptions` each create request-scoped
  `AgentRunContext`, `AgentTraceWriter`, and correction adapter.
- Runtime trace payloads exclude raw metric deltas, causal-attribution details,
  secret-like keys, and full feedback/adoption payloads.
- Existing run traces are preserved when later correction denial is appended.
- HTTP correction routes attach checkpoint stores, and correction tools set
  `preserve_result_on_checkpoint_failure=True`, so a checkpoint backend failure
  after completed adoption preserves the completed response while retaining safe
  `agent_runtime.checkpoint_failed` evidence.
- Self-report feedback checkpoint replay cannot be reused as external adoption.
- External adoption cannot be written through `record_outcome`.
- Unknown trace correction does not fabricate a `KnowledgeAsset`.

## Engineering Reality Gate

Entry point:

- `POST /outcomes`
- `POST /adoptions`

Contract:

- `AgentRunContext`
- `ToolSpec`
- `AgentToolCall`
- `AgentToolResult`
- `OutcomeResponse`
- `AdoptionResponse`

Failure mode:

- Missing principal/context, paused shell, missing runtime permission, risk
  ceiling violation, validation failure, tool error, and explicit checkpoint
  mismatch tests are denied or surfaced through typed runtime results before
  unsafe writes.

Test validity:

- The new tests would fail if HTTP routes called `record_outcome_service` or
  `attest_adoption_service` directly, skipped `RuntimePolicyGate`, wrote while
  paused, promoted self-report as adoption, leaked raw runtime payloads, or
  overwrote existing `RunTrace` evidence.

Integration:

- The slice calls the real `TrustedLoopRuntime`, `FeedbackStore`,
  `AdoptionIngest`, `KnowledgeStore`, and `RunTrace` persistence path.

Boundary:

- No external agent framework dependency was introduced.
- No cross-repo import was introduced.
- No autonomous-core claim is made.
- No automatic R4/R5 action execution is introduced.

Observability:

- Correction-channel allow/deny/success/failure is trace-visible through safe
  `agent_runtime.*` events, appended to the existing run trace when one exists.

Product/process boundary:

- This is a product runtime behavior inside the deployment layer. It is not
  evidence that autonomous intelligence is achieved, and it is not meta-layer
  workflow automation.

## Residual Risks

- This is branch-local self-review, not independent review.
- `external_value_attestation` is allowed without `approval_id` only because the
  current HTTP authorization model treats `adoptions:write` as the realized-value
  authority. If the adoption surface becomes externally delegated or higher
  risk, a future slice should consider operator-key-only adoption or an explicit
  correction approval context.
- The runtime still does not implement true wall-clock preemption, streaming
  cancellation, public resume API, production telemetry export policy, or
  workflow-engine semantics.

## Gate Outcome

Outcome: ACCEPTABLE FOR LOCAL MERGE DECISION; LOCAL MERGE COMPLETED AFTER FOUNDER/CTO AUTHORIZATION.

Post-merge `make ci` and `ci-local-full` passed on local `main`. Do not push,
release, or describe this work as externally shipped unless a later release gate
explicitly authorizes it.
