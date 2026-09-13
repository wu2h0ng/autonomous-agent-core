# Subagent Adversarial Review — SRL TaskActivationGate

> Reviewer: opencode built-in `general` subagent (SAME model/provider as builder opencode/deepseek-v4-flash)
> Independence: **INSUFFICIENT for a formal `builder_id != reviewed_by` gate** — additional adversarial pass only.
> Subject: `feature/srl-closed-loop-1-20260913`, base `0045aeea` → HEAD `ef95ff82`.
> Verdict: **APPROVE_WITH_CHANGES**

## Verification (reviewer-run)

- `test_srl_task_activation_gate.py` + `test_srl_runtime_invariants.py`: 53 passed (39 invariants green). Ruff clean. No files modified.

## Findings

### H1 — MEDIUM — I-23 is fail-open when `assessor-instance:` metadata is absent/forged
`srl_activation_gate.py:161-167` (helper `:235-240`); same pattern `srl_runtime.py:316-320`/`:435-440`.
Producer/acceptor separation derives solely from a caller-supplied `ProposedGoal.constraints` string. If the constraint is missing, `producer_instance_id is None` and the check is skipped (`if producer_instance_id is not None and ...`) → fails OPEN.
Reproduced: with a trusted authority whose `authority_instance_id == "assessor-instance-1"`, activation is denied when the constraint is present but succeeds when the caller strips the `assessor-instance:` constraint.

### H2 — MEDIUM — Authority/goal mandate binding is never verified
`srl_activation_gate.py:176-188`; goal carries `mandate-ref:` at `srl_goal_formation.py:60`.
The gate checks the authority's mission against the authority's own mandate, and mandate tenant/workspace against the goal, but never binds `authority.mandate_id` to the goal's `mandate-ref:`. Reproduced: cross-mandate authority (same tenant/workspace) → `activated=True`.

### H3/H4 — LOW — `source_assessment_id`/`authorization_digest` unverified; C7 clearance identity only epoch-checked. Latent under the stated boundary.
### H5 — INFO — unused `TRUSTED_AUTHORITY_MISSING` / `CreatedTask.run_id`; missing tests for digest mismatch, scope/mission mismatch, `MANDATE_UNAVAILABLE`, stripped-producer (H1), cross-mandate (H2).

## Required changes

1. H1 (blocking): make I-23 fail-closed — reject when producer identity is absent, and/or derive producer from the trusted `source_assessment_id` registry rather than forgeable goal constraints. Add the stripped-constraint test.
2. H2 (recommended): enforce `authority.mandate_id` against the goal's `mandate-ref:` constraint; add a cross-mandate test.
3. H5 (recommended): add the missing branch tests; remove/wire unused members.

Confirmed correct: F1 fail-closed fix, identical-input idempotency, no caller-minted authority to TaskService, C7 untouched, 39 invariants pass. Git: no push/merge.
