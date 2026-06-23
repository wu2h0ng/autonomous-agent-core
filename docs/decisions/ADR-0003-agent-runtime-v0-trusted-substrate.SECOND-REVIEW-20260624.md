# ADR-0003 Second Review: Agent Runtime v0 Trusted Substrate

- Review date: 2026-06-24
- Branch reviewed: `codex/agent-runtime-v0-trusted-substrate`
- Reviewed range: `590df9f..addcc48`
- Base review: `ADR-0003-agent-runtime-v0-trusted-substrate.REVIEW-20260624.md`
- Remediation record: `ADR-0003-agent-runtime-v0-trusted-substrate.CODEX-REMEDIATION-20260624.md`
- Approval status: **APPROVED WITH FOLLOW-UP**

## Findings

### M1 - Real TrustedLoop adapter coverage remains follow-up

- Severity: MEDIUM / follow-up, non-blocking for H1-H3 remediation
- File: `tests/integration/test_trusted_loop_agent_runtime_adapter.py`
- Spec reference: `docs/decisions/ADR-0003-agent-runtime-v0-trusted-substrate.SPEC.md`

The adapter test still uses a fake loop and does not prove a real `TrustedLoopRuntime.evaluate()` path preserves SQL Safety and EvidenceChain behavior through the adapter. This was already identified in the first review and was not introduced by the H1-H3 remediation.

Required follow-up:

- Add a real minimal `TrustedLoopRuntime` adapter integration test in a later patch before expanding runtime adoption.

### L1 - README verification count drift

- Severity: LOW / fixed after second review
- File: `README.md`

The Stage 1 paragraph still said 429 tests OK while the remediation record and `CURRENT_STATE.yaml` said 434 tests OK. This was corrected after the second review.

## H1-H3 Recheck

- H1 closed: `AgentRuntime.run_tool()` now delegates to `invoke_tool()` and no longer bypasses context validation, pause checks, policy, validation, trace, or checkpointing.
- H2 closed: `RuntimePolicyGate` requires `approval_id` for R4/R5 and side-effecting tools, even when the tool author does not set `requires_approval=True`.
- H3 closed: runtime trace events no longer record raw args or raw output by default, so TrustedLoop parameters/results and secret-like fields are not emitted through runtime trace projection.

The H1-H3 regression tests use the real runtime, tool registry, policy gate, and trace writer; they are not pure mock self-tests.

## Verification

Second-review spot checks:

```text
targeted runtime tests: 19 OK
git diff --check: clean
worktree: clean at reviewed commit
```

Codex remediation verification:

```text
make ci: ruff clean, format clean, 434 tests OK, 4 skipped, 12 eval tests OK, OpenAPI clean
ci-local-full: passed against disposable PostgreSQL on 127.0.0.1:15432
```

## Approval Status

ADR-0003 H1-H3 remediation is **approved with follow-up**. No merge blocker remains from the H1-H3 review gate.

Merge to `main` still requires explicit founder/CTO authorization under the Git finalization gate.
