# P-SRL-RUNTIME-1 M0 Implementation Log

## Status
M0 implementation complete and verified locally.

## What changed

### New os_core modules
- `packages/os_core/src/agent_os_core/srl_runtime.py` — public `SrlRuntime` orchestrator with fail-closed `evaluate_event`, `propose_goal`, `activate_goal`, `emit_help_request`, `resolve_help_request`, `accept_outcome`.
- `packages/os_core/src/agent_os_core/srl_ports.py` — `ContractModel` result types, `ActivationAuthority`, `TrustedOutcomeRecord`, `AuditTransition`, and all internal `Protocol` ports.
- `packages/os_core/src/agent_os_core/srl_event_ledger.py` — in-memory deduplicated event ledger.
- `packages/os_core/src/agent_os_core/srl_mandate_registry.py` — in-memory ratified Mandate/StandingMission registry with parent-digest and status checks.
- `packages/os_core/src/agent_os_core/srl_budget_ledger.py` — per-binding wake/query counters and per-mandate help burden ledger.
- `packages/os_core/src/agent_os_core/srl_help_dispatch.py` — help request store with continuable-work expiry rules.
- `packages/os_core/src/agent_os_core/srl_goal_formation.py` — ProposedGoal formation with read-only binding write-effect rejection.
- `packages/os_core/src/agent_os_core/srl_outcome_acceptor.py` — trusted-evaluator-registry outcome acceptance stub.
- `packages/os_core/src/agent_os_core/srl_audit.py` — non-erasable in-memory audit log stub.
- `packages/os_core/src/agent_os_core/srl_assessor.py` — fixed-policy assessor stub used by tests.
- `packages/os_core/src/agent_os_core/srl_task_activation.py` — in-memory task activation stub that rejects capability-grant creation.

### Contract amendment
- `packages/contracts/src/agent_os_contracts/srl_help.py` — added optional `tenant_id` and `workspace_id` fields to `SrlHelpRequest` so mandate-scoped help requests carry provenance without breaking existing R-SRL-1 harness callers.

### Tests
- `tests/product/test_srl_runtime_invariants.py` — 14 RED tests covering A-SRL-1 RT invariants I-4, I-8, I-11, I-12, I-13, I-14, I-15, I-16, I-18, I-20, I-21, I-22, I-23, I-25.

## Key design decisions
- M0 stays in-memory, provider-free, and TaskService-free; all authority transitions are recorded through the injected `AuditPort`.
- `SrlRuntime` does not register bindings automatically; `SrlGoalFormation` exposes `add_binding_for_event` so tests can model read-only vs write-capable bindings explicitly.
- Write-effect CREATE_TASK proposals on read-only bindings raise `SituationalTrustDenied`, preserving the authority boundary.
- `emit_help_request` reconstructs the immutable `HelpDispatchResult` with the ledger-computed `HelpBurdenReceipt` (I-21), rather than mutating the port result.

## Commands run
```bash
python -m pytest tests/product/test_srl_runtime_invariants.py -v
ruff check packages/os_core/src/agent_os_core/srl_*.py tests/product/test_srl_runtime_invariants.py packages/contracts/src/agent_os_contracts/srl_help.py
ruff format packages/os_core/src/agent_os_core/srl_*.py tests/product/test_srl_runtime_invariants.py packages/contracts/src/agent_os_contracts/srl_help.py
.venv/bin/python -m pyright packages/os_core/src/agent_os_core/srl_*.py packages/contracts/src/agent_os_contracts/srl_help.py
python -m pytest tests/product -q
```

## Results
- `tests/product/test_srl_runtime_invariants.py`: 14 passed
- `tests/product/`: 756 passed, 1 skipped (no regressions; +14 from new M0 tests)
- `pyright` on new files: 0 errors, 0 warnings
- `ruff check` on new files: clean
- `ruff format`: clean

## Boundaries preserved
- No persistence, no provider calls, no TaskService integration.
- No real capability grants, ActionPermit, or ActionReceipt creation from SRL organs.
- No main-branch merge or push.
- No autonomy, AGI, or production-readiness claim.
