# Task 5 report — admission-required MandateSteward

## Scope

- Added the proposal-only `MandateSteward` public facade.
- Added a private structural trace-writer port; the facade does not import or expose the concrete writer.
- Added module-level refcounted process-wide single-flight keyed by the receipt/projection trace identity.
- Added durable PENDING creation, pre-delegation attempt increment, persisted-record reconciliation, terminal replay, authority-drift denial, and immutable result binding.
- Exported only `MandateSteward` from `agent_os_core`.

No provider implementation, connector, capability, Task activation, external effect, merge, push, or release path was added.

## Truth and failure boundaries

- A current ratified mandate/binding is re-read before every new or replayed observation.
- The admission receipt is checked against the exact trusted event, principal, tenant/workspace, mandate, binding version/digest, correction epoch, projection scope/source, and trusted binding.
- `SituatedAssessmentRecord` is the only result truth. A service return without a record, a constant/mismatched return, a changed record, or a changed terminal result digest fails closed.
- A `PENDING + record` crash window reconciles without another delegation or attempt increment.
- An uncommitted delegate exception leaves an incremented PENDING trace and emits no provider-total claim.
- Provider latency is excluded from `duration_ms`; token fields remain `None`; committed provider-call status is copied only from a persisted assessment.
- `ABSTAIN` is a completed `NO_PROPOSAL`, not a denial.

## Tests

Focused Task 5:

```text
15 passed
```

Task 1-5 plus situated/provider/M0-adjacent suites:

```text
437 passed
```

Full Product suite:

```text
1012 passed, 1 skipped
```

Static verification:

```text
ruff: all checks passed
pyright: 0 errors, 0 warnings, 0 informations
git diff --check: passed
```

The first focused run exposed and corrected one test-fixture database-directory defect; no product behavior was claimed from that run. The final focused suite covers the disposition matrix, replay, missing admission material, two-facade single-flight, no-record and returned-result mismatch, transition-failure restart reconciliation, uncommitted crash window, authority drift, record mutation, and forbidden imports.

## Files

- `packages/os_core/src/agent_os_core/mandate_steward.py`
- `packages/os_core/src/agent_os_core/__init__.py`
- `tests/product/test_mandate_steward.py`
- `.superpowers/sdd/task-5-report.md`

## Remaining authority boundary

This task produces proposal-only `TaskDraftProposal | HelpRequest | None`. It does not activate a Goal, Commitment, ExpectedOutcome, WorkflowGraph, PolicyKernel, CapabilityBroker, Task, provider, connector, or external effect.
