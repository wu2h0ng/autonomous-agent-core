# ADR-0004 governed-decision seam review (2026-07-02)

## Scope

- Branch: `feature/governance-decision-seam-2026-07-01`
- Base: deployment local `main@91ae01c`
- Reviewer: Claude Code independent diff review, then Codex remediation and verification
- Scope reviewed: ADR-0004/RR-0032 R0-R3 governed-decision seam code, contract, tests, and status docs

## Findings

1. MEDIUM - `TrustedLoopRuntime` only blocked `DENY` and forced approval for `ESCALATE`/`VERIFY_MORE`; any unknown verdict silently behaved like `ALLOW`.
   - Disposition: fixed. Unknown verdicts now normalize to `VERIFY_MORE`, force approval, avoid connector execution, and do not write the raw verdict into trace.

2. MEDIUM - `RemoteGovernanceDecisionClient` trusted remote responses without checking response `task_id`, response contract major version, verdict membership, or `audit_ref`.
   - Disposition: fixed. Remote responses now validate those fields and raise before returning to the Trusted Loop; the runtime catches the failure and fail-closes to approval.

3. LOW - Remote free-text `reason` was written directly to `RunTrace` and `GOVERNANCE_DENIED` block details.
   - Disposition: fixed. Runtime trace and block details now use a fixed withheld-reason projection while preserving `audit_ref` for controlled audit lookup.

4. LOW - The seam runs at initial proposal time; approval-resume/execution does not re-consult the seam.
   - Disposition: accepted boundary for this R0-R3 slice. R4/R5 still remain proposal-only and approval-bound. Execution-time recheck needs a follow-up ADR/gate if required for a live use-case.

## Verification

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:action_connectors:apps/api_server/src \
  .venv/bin/python3 -m unittest tests.unit.test_governance_decision_seam \
  tests.unit.test_trusted_loop tests.integration.test_trusted_loop_agent_runtime_adapter -v
make ci PYTHON=.venv/bin/python3
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
  make ci-local-full PYTHON=.venv/bin/python3
```

Result: targeted seam/adjacent suite 50 tests OK; `make ci` passed with ruff clean, format clean, 534 tests OK / 4 skipped, 12 eval OK, and OpenAPI up to date; PostgreSQL `ci-local-full` passed with the same 534 tests OK / 4 skipped, 12 eval OK, and OpenAPI up to date.

## Verdict

Review findings are remediated for the branch-local ADR-0004 scope. This is not merge, push, release, production remote-service wiring, production auth/service identity, or autonomous-core evidence validation.
