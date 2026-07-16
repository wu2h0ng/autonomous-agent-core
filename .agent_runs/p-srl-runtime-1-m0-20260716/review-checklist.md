# P-SRL-RUNTIME-1 M0 Review Checklist

> For use after coder subagent completes implementation.

## 1. Scope and boundaries
- [ ] Only the specified files were created/modified.
- [ ] No existing tests or contracts were changed.
- [ ] No provider calls, database writes, or TaskService integration.
- [ ] No real capability grants, ActionPermit, or ActionReceipt creation from SRL organs.

## 2. Architecture alignment
- [ ] `SrlRuntime` public methods match design: `evaluate_event`, `propose_goal`, `activate_goal`, `emit_help_request`, `resolve_help_request`, `accept_outcome`.
- [ ] All internal ports are defined as Protocols in `srl_ports.py`.
- [ ] In-memory stubs are deterministic and isolated per Runtime instance.
- [ ] No single `instance_id` both produces evidence and emits acceptance authority.

## 3. RT invariant RED tests
- [ ] I-4: `StandingMission` parent digest mismatch rejected.
- [ ] I-8: Assessor policy digest mismatch rejected.
- [ ] I-11: Help burden flips to `EXCEEDED`.
- [ ] I-12: Duplicate `dedupe_key` rejected/idempotent.
- [ ] I-13: Wake/query budget exhaustion returns `BUDGET_HALT`.
- [ ] I-14: SRL organ cannot create `CapabilityGrant`/`ActionPermit`/`ActionReceipt`.
- [ ] I-15: Untrusted `ObservedOutcome` rejected.
- [ ] I-16: Non-RATIFIED/ACTIVE/expired Mandate rejects mission.
- [ ] I-18: Read-only binding rejects write-effect proposal.
- [ ] I-20: After help expiry, only `continuable_work` continues.
- [ ] I-21: Help burden computed by separate ledger, not emitter.
- [ ] I-22: W1/W2 updates cannot mutate Mandate/Envelope/Mission/grants.
- [ ] I-23: Same instance cannot produce assessment and accept authority.
- [ ] I-25: Cross-restart replay with same dedupe_key is idempotent.

## 4. Fail-closed behavior
- [ ] Unknown disposition → `ABSTAIN`.
- [ ] Policy digest mismatch → reject assessment, increment help metrics.
- [ ] Budget exceeded → halt binding, emit HELP/REVOCATION_REQUEST.
- [ ] Untrusted outcome → reject.
- [ ] C7 check failure → halt affected action.

## 5. Quality gates
- [ ] `ruff check packages/os_core/src/agent_os_core/srl_*.py tests/product/test_srl_runtime_invariants.py` passes.
- [ ] `pyright packages/os_core/src/agent_os_core/srl_*.py tests/product/test_srl_runtime_invariants.py` passes.
- [ ] `pytest tests/product/test_srl_runtime_invariants.py -v` passes.
- [ ] `pytest tests/product/ -q` shows no regressions.

## 6. Documentation
- [ ] `implementation-log.md` lists files changed and commands run.
- [ ] `verification.md` contains ruff/pyright/pytest output.
- [ ] Docstrings explain public classes and methods.

## 7. Verdict options
- `APPROVE_M0` — all checks pass, ready to commit.
- `REVISE` — specific defects listed; return to coder for fix.
- `REJECT` — fundamental architecture drift; discard and redesign.
