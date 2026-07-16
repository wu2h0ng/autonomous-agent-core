# P-SRL-RUNTIME-1 M0 Implementation Brief

## Goal
Implement the M0 milestone of P-SRL-RUNTIME-1: a minimal SRL Runtime with typed internal ports, in-memory stubs, and RED tests for the A-SRL-1 RT invariants. No persistence, no provider calls, no TaskService integration.

## Scope
- `packages/os_core/src/agent_os_core/srl_runtime.py` — public orchestrator
- `packages/os_core/src/agent_os_core/srl_ports.py` — Protocol definitions
- `packages/os_core/src/agent_os_core/srl_event_ledger.py` — in-memory event ledger
- `packages/os_core/src/agent_os_core/srl_mandate_registry.py` — in-memory mandate/mission registry
- `packages/os_core/src/agent_os_core/srl_budget_ledger.py` — in-memory wake/query/help budget ledger
- `packages/os_core/src/agent_os_core/srl_help_dispatch.py` — help request lifecycle stub
- `packages/os_core/src/agent_os_core/srl_goal_formation.py` — proposed goal formation stub
- `packages/os_core/src/agent_os_core/srl_outcome_acceptor.py` — trusted outcome acceptor stub
- `packages/os_core/src/agent_os_core/srl_audit.py` — non-erasable audit log stub
- `tests/product/test_srl_runtime_invariants.py` — RED tests for I-4, I-8, I-11-I-25

## Acceptance Criteria
1. All new modules are typed, have docstrings, and follow the existing `agent_os_core` style.
2. `SrlRuntime.evaluate_event` returns a typed `SrlEvaluationResult` with no side effects beyond audit logging.
3. Every RT invariant from A-SRL-1 §5 has a failing RED test that passes only when the Runtime enforces it.
4. No provider calls, no database writes, no TaskService calls, no C7 bypass, no capability grant creation.
5. `ruff` and `pyright` clean on new files.
6. Existing Product tests continue to pass.

## Boundaries
- DESIGN_ONLY → IMPLEMENTED_LOCAL for M0 only.
- No main merge, no push, no production claim.
- Preserve all existing contracts and tests.
