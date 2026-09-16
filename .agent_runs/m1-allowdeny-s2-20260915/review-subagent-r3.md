# Independent adversarial THIRD exact-diff review — M1 S2 DENY-only rules (r2 fix)

> Reviewer: subagent (adversarial, exact-diff)
> Model: deepseek-flash — **SAME MODEL as builder** (see §0)
> Worktree: `autonomous-agent-core/.worktrees/m1-danger-cmd-20260915`
> Commit under review: `9744f8d1` ("fix(terminal-m1): S2 r2 review — only block APPROVE,
> keep REJECT resolvable"); parent `01c23005`; branch base `origin/main` `18d7b9b0` (not merged).
> Prior report: `.agent_runs/m1-allowdeny-s2-20260915/review-subagent-r2.md`
> Scope of write: this file only. All source/test files treated READ-ONLY; worktree clean.

## 0. Independence limitation (recorded)

Root `AGENTS.md` §11 requires `builder_id != reviewed_by`. I am the **same model as the
builder** (deepseek-flash), as in every prior S1/S2 round. This review is therefore **not
independent** and cannot by itself satisfy the independent exact-diff promotion gate. A
different model or a human must confirm before promotion/push/merge.

## 1. Exact-diff binding

`git diff 01c23005..9744f8d1` = 3 files, +182 / −20 (`git diff --stat`):

- `.agent_runs/.../review-subagent-r2.md` (prior report, committed alongside the fix)
- `packages/os_core/src/agent_os_core/agent_loop.py` (+22 / −20: the deny block is moved and
  gated on `APPROVE`, and now sits *after* the unknown-reconciliation check)
- `tests/product/test_permission_deny_rules.py` (+28: one new test)

`git diff --check 01c23005..9744f8d1` → clean (exit 0). `ruff` on both changed code/test files
→ `All checks passed!`. `pyright agent_loop.py` → `0 errors`.

`permission_gate.py`, `permission_rules.py` and `tests/product/test_permission_mode_matrix.py`
are **untouched** by this commit (`git diff` over those paths is empty).

## 2. Requested r2 findings — CLOSED / OPEN

| r2 finding | Status | Evidence (independently re-verified) |
|---|---|---|
| **MEDIUM — pending-approval deny check ran before the disposition branch, so a matching DENY rule also blocked REJECT (pending approval wedged until rule revoked)** | **CLOSED** | `agent_loop.py:574-595`: the deny lookup/raise is now nested under `if approval.disposition is ApprovalDisposition.APPROVE:`. Only APPROVE executes, so only APPROVE is gated. Probe (real `AgentOSApplication`, tier-3 `workspace.shell`, rule saved post-escalation, exact **and** `*` wildcard): APPROVE → `RunExecutionError` + durable `POLICY_VERDICT_RECORDED(verdict=DENY,basis=rule,rule_id=rule-1)`, 0 receipts; REJECT → `stop_reason=completed`, pending continuation cleared, 0 receipts, 0 rule-deny verdicts. New test `test_deny_rule_does_not_wedge_a_reject` (`:352`) exercises the exact wedge; it is bypass-detecting by construction (under `01c23005`'s unconditional pre-disposition check the call raises `RunExecutionError`, failing the test). |
| **LOW — deny check preceded the unknown-reconciliation check, shadowing `unknown_requires_review`** | **CLOSED** | The `_unknown_session_action` block now runs at `agent_loop.py:541-573`, **before** the deny block at `:574`. Probe: drive a deferred edit into `CapabilityEffectUnknown` (dispatch raises after writing), then save a `*` rule and retry APPROVE → `stop_reason="unknown_requires_review"` both before and after the rule is added (no `RunExecutionError`). Fail-closed, recovery signal preserved. |

## 3. Required invariant checks (a)–(f)

- **(a) REJECT resolves under a matching rule (no wedging)** — **PASS**. Exact and `*`-wildcard
  rules both yield `stop_reason=completed`; pending cleared; no receipt; no deny verdict.
- **(b) APPROVE is still blocked** — **PASS**. `RunExecutionError`, durable rule-attributed
  DENY verdict, no receipt.
- **(c) unknown path still surfaces `unknown_requires_review`** — **PASS** (see §2 LOW).
- **(d) no rule path can ALLOW / auto-approve tier-3 / pre-empt C7** — **PASS**. `apply_deny_rules`
  can only return the original decision or `DENY_BY_RULE`; `PermissionRuleKind == ["DENY"]`.
  Probe over 7 allowlisted capabilities + 1 unknown × 3 modes with a `*` rule → allow-leaks `[]`.
  The resume-side check only raises; C7 epoch/halt validation (`_validate_pending_runtime`,
  `require_current_c7=True`) still runs for APPROVE after the deny check.
- **(e) empty `deny_rules` byte-identical** — **PASS** at the decision level. `apply_deny_rules`
  with `rules=()` returns the *identity* object for 4 capabilities × 3 modes
  (`empty-denyrules identity: True`); with empty rules the moved APPROVE check returns `None`,
  so behaviour is unchanged, and REJECT skips a no-op.
- **(f) frozen matrix unchanged** — **PASS**. `permission_gate.py` and
  `test_permission_mode_matrix.py` are not in the diff; `evaluate_permission_gate` body is
  untouched. Matrix tests 7 passed.

## 4. Test runs (exact)

```
uv run --extra product-test pytest tests/product/test_permission_deny_rules.py \
  tests/product/test_permission_mode_matrix.py tests/product/test_terminal_chat_loop.py -q
```

→ **54 passed in 3.71s**. Per file:

- `test_permission_deny_rules.py` → **12 passed** (was 11 at `01c23005`)
- `test_permission_mode_matrix.py` → **7 passed** (frozen matrix)
- `test_terminal_chat_loop.py` → **35 passed**

`ruff` (2 changed files) → pass; `pyright agent_loop.py` → 0 errors.

## 5. New findings

1. **[LOW — weak assertion on the new anti-wedge test]** `test_deny_rule_does_not_wedge_a_reject`
   asserts only `result is not None`. A future regression that *returns* a `TurnResult`
   (e.g. `unknown_requires_review`, or a REJECT resolved without clearing the pending
   continuation) rather than raising would still pass. It does catch the exact r2 regression,
   but should assert `result.stop_reason == "completed"` and that
   `project_session(...).pending_continuation is None`. Test-only; no runtime impact.
2. **[LOW — residual r2 NEW-4 test gap, still OPEN]** The r2 verdict required "add a SELFDEV
   deny-rule test (or explicitly scope the claim)". Neither was done in `9744f8d1`. Wiring
   exists (`responsibility_surface.py:629-635`) but **no test** asserts that a deny rule blocks
   a SELFDEV `resume_pending_approval`/execution or that the SELFDEV REJECT stays resolvable.
3. **[INFO — narrow TOCTOU snapshot, pre-existing pattern, not actionable]** `decide_session_approval`
   rebuilds the loop with a fresh `list_active` snapshot, so a rule added *before* the call is
   seen and revocation is honored (probe: revoke rule → APPROVE completes). A rule inserted in
   the sub-millisecond window between snapshot and `resume_pending_approval` is not seen; the
   same loop-consistent-snapshot pattern governs the whole turn path. Fail-safe only in the
   revocation direction; noted for completeness, not a defect of this commit.
4. **[INFO — dangling-claim + incoming REJECT, pre-existing]** If a durable
   `SESSION_APPROVAL_EXECUTION_CLAIMED` from a prior APPROVE dangles, an incoming REJECT would
   skip the (now APPROVE-only) deny check and `record_or_reuse_session_approval` returns the
   claimed APPROVE. To complete it, `reconcile_before_policy` must return non-`None`, i.e. the
   effect already happened — recovery, not a fresh effect; and it predates this commit. No new
   effect can be produced. Recorded as INFO.

No new MEDIUM/HIGH finding. No ordering, disposition, C7 or revocation-race defect introduced.

## 6. Verdict

**APPROVE_WITH_CHANGES**

Both targeted r2 findings are **CLOSED** with independent probes and a bypass-detecting test:
REJECT is no longer wedged by a matching rule, APPROVE still fails closed with durable
rule-attributed provenance, `unknown_requires_review` is no longer shadowed, no rule can ALLOW /
auto-approve tier-3 / pre-empt C7, empty-rule decisions are identity-identical and the frozen
matrix is unchanged. Residual work is **test-only, non-runtime**: strengthen the REJECT
assertion (NEW-1) and add the still-missing SELFDEV deny-rule test or scope the claim to chat
paths (NEW-2), which r2 had already required before promotion.

Per §0 this review is **not independent**; an independent model/human must confirm before
promotion/push/merge.
