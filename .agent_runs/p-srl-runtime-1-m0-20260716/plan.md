# P-SRL-RUNTIME-1 M0 Implementation Plan

## Step 1: Inspect existing patterns (read-only)
- Read `packages/os_core/src/agent_os_core/__init__.py`, `errors.py`, `task_service.py`, `execution.py`
- Read `packages/contracts/src/agent_os_contracts/mandate.py`, `srl_environment.py`, `srl_help.py`
- Read `tests/product/test_mandate_contracts.py`, `test_srl_environment_contracts.py`
- Read `pyproject.toml` for ruff/pyright config

## Step 2: Define result models
- Add `SrlEvaluationResult`, `TaskActivationResult`, `HelpDispatchResult`, `OutcomeAcceptanceResult`, `ActivationAuthority`, `TrustedOutcomeRecord`, `AuditTransition` to `srl_ports.py` as `ContractModel` subclasses.

## Step 3: Define port Protocols
- Create `srl_ports.py` with all Protocol classes and result models.

## Step 4: Implement in-memory stubs
- `srl_event_ledger.py`: dict-based ledger with dedupe_key uniqueness per binding.
- `srl_mandate_registry.py`: dict-based registry with ratified Mandate and StandingMission versions; validates parent digest, status and expiry.
- `srl_budget_ledger.py`: per-binding wake/query counters and per-mandate help burden ledger.
- `srl_help_dispatch.py`: help request store with continuable_work tracking.
- `srl_goal_formation.py`: form ProposedGoal, reject disallowed task classes and write effects on read-only bindings.
- `srl_outcome_acceptor.py`: accept only records signed by trusted evaluator registry.
- `srl_audit.py`: in-memory list of AuditTransition records.

## Step 5: Implement public Runtime
- `srl_runtime.py`: `SrlRuntime` class with all public methods.
- Enforce authority separation and fail-closed behavior.
- Use `AuditPort` at every transition.

## Step 6: RED tests
- `tests/product/test_srl_runtime_invariants.py`: one test per RT invariant.
- Tests should fail if the Runtime bypasses the invariant.

## Step 7: Static checks
- Run `ruff check packages/os_core/src/agent_os_core/srl_*.py tests/product/test_srl_runtime_invariants.py`
- Run `pyright packages/os_core/src/agent_os_core/srl_*.py tests/product/test_srl_runtime_invariants.py`

## Step 8: Product regression
- Run `pytest tests/product/ -q` to ensure no regression.

## Step 9: Record implementation log and verification
- Write `.agent_runs/p-srl-runtime-1-m0-20260716/implementation-log.md`
- Write `.agent_runs/p-srl-runtime-1-m0-20260716/verification.md`
