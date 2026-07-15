# Product Materialization Evaluation Clock Drift Fix

> Date: 2026-07-16
> Track: Product / low-risk deterministic testability repair
> Exact base: `e1343e3da66414c5bb944420432bf03f66ff4cfb`
> Scope: Agent OS composition-root clock seam and materialization evaluation API regressions
> Authority: implementation evidence only; not a CURRENT_STATE, release, migration, or capability claim

## Root cause

`tests/product/test_materialization_evaluation_api.py` reused the service-test constant
`NOW = 2026-07-15T14:00:00Z` to create all Task, Run, grant, provenance, and
evaluation fixtures. The resulting evaluation grant expired at `15:00Z` and the
Task Commitments expired at `16:00Z`.

The service tests were deterministic because both `TaskService` and
`DomainCandidateEvaluationRecorder` received `clock=lambda: NOW`. The HTTP test
constructed `AgentOSApplication` instead. That composition root did not expose a
clock parameter and independently constructed its Task service and materialization
services with real UTC wall-clock defaults.

The failure therefore moved as wall clock crossed two thresholds:

1. after `15:00Z` but before `16:00Z`, fixture Task startup still succeeded but
   evaluation recording rejected the expired grant, producing two unexpected HTTP
   `403` responses;
2. at or after `16:00Z`, fixture Task startup rejected the expired Commitment, so
   all three API tests failed during setup with `CommitmentExpiredError`.

The production expiry comparisons were correct. The defect was that one
composition root mixed static fixture timestamps with independent real-time clocks.

## Investigation and hypothesis check

- Exact reproduction before the fix:
  `uv run --extra product-test pytest tests/product/test_materialization_evaluation_api.py -q -vv --tb=long`
  produced three setup errors at `TaskService.start_run`.
- Existing injected-clock comparison:
  `uv run --extra product-test pytest tests/product/test_materialization_evaluation_service.py -q`
  produced `12 passed` with the same static contracts.
- Single hypothesis: exposing one clock at `AgentOSApplication` and passing that
  exact callable to Task and materialization authority services removes host-time
  drift while retaining fail-closed expiry behavior.

## RED to GREEN

The deterministic regression first failed three cases with
`TypeError: AgentOSApplication.__init__() got an unexpected keyword argument 'clock'`.
It covers two valid frozen instants (`14:00Z`, `14:30Z`) and asserts that both Task
events and evaluation receipts use the selected instant. A separate case advances
the same explicit clock past the grant and Commitment boundaries and requires the
existing typed denials.

The minimal repair adds a default-real-UTC clock seam to `AgentOSApplication`,
passes it to `TaskService`, `DomainCandidateSealer`,
`DomainCandidateEvaluationRecorder`, `DomainCandidatePromotionService`, and
`TaskConfigurationSnapshotService`, and uses it when rebuilding composition-root
grants. Default production behavior remains real UTC and continues to reject
expired grants and Commitments.

## Claim ceiling

This repair establishes deterministic composition-root time alignment for the
covered Product services and removes a calendar-dependent Product test failure. It
does not change grant duration, Commitment duration, C7, permission policy,
provider behavior, materialization semantics, production readiness, release state,
or any research claim.
