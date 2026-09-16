# Independent adversarial RE-REVIEW — M1 S2 DENY-only rules (fix commit)

> Reviewer: subagent (adversarial, exact-diff)
> Model: deepseek-flash — **SAME MODEL as builder** (see §0)
> Worktree: `autonomous-agent-core/.worktrees/m1-danger-cmd-20260915`
> Commit under review: `01c23005` ("fix(terminal-m1): S2 review — enforce deny rules on the
> pending-approval path, preserve denial provenance")
> Parent: `f8a8a324`; branch base `origin/main` merge-base `18d7b9b0` (origin/main has since
> advanced to `dd61fa02`; not merged)
> Prior report: `.agent_runs/m1-allowdeny-s2-20260915/review-subagent.md`
> Scope of write: this file only. All source/test files treated READ-ONLY (worktree clean).

## 0. Independence limitation (recorded)

Root `AGENTS.md` §11 requires `builder_id != reviewed_by`. I am the same model as the builder
(deepseek-flash), as in every prior S1/S2 round. This re-review is **not independent** and
cannot by itself satisfy the independent exact-diff gate. A different model or a human must
confirm before promotion/push/merge.

## 1. Exact-diff binding

`git diff f8a8a324..01c23005` = 5 files, +303 / −4:

- `.agent_runs/.../review-subagent.md` (the prior report, committed here)
- `packages/os_core/src/agent_os_core/agent_loop.py`
- `packages/os_core/src/agent_os_core/permission_gate.py`
- `packages/os_core/src/agent_os_core/responsibility_surface.py`
- `tests/product/test_permission_deny_rules.py`

`git diff --check f8a8a324..01c23005` → clean (exit 0). `ruff` on all four code/test files →
pass. `pyright responsibility_surface.py` → 0 errors.

## 2. Prior findings — CLOSED / OPEN

| Prior finding | Status | Evidence (re-verified) |
|---|---|---|
| **1 MEDIUM** pending-approval path ignored deny rules (fail-open) | **CLOSED** | `agent_loop.py:541-560` now calls `active_deny_rule(self._deny_rules, pending.action.capability_id, principal.tenant/workspace)`; on match it records `POLICY_VERDICT_RECORDED(verdict=DENY, basis=rule, rule_id=…)` (durable) and raises `RunExecutionError` before any dispatch/C7 path. Loop is rebuilt on `decide_session_approval` → `restore_chat_session` with a **fresh** `list_active` (`app.py:2095`), so a rule added *after* escalation is seen. New test `test_deny_rule_blocks_resolving_a_pending_approval` asserts the durable `basis=rule` verdict + `rule_id`, and **fails on revert** (see §4). |
| **2 MEDIUM** SELFDEV `AgentLoop` lacked `deny_rules` | **CLOSED (wiring) / residual LOW test gap** | `responsibility_surface.py:629-635` passes `deny_rules=execution_app.permission_rule_store.list_active(tenant, workspace)` guarded by `getattr(..., None) is not None`. All three `AgentLoop(` sites in the repo are now wired. **No test asserts the SELFDEV deny behaviour** (the prior "plus a test" clause is unmet). |
| **3 LOW** `*` wildcard relabelled `DENY_OUT_OF_ALLOWLIST` | **CLOSED** | `permission_gate.py:101-107` early-returns unchanged for `DENY_OUT_OF_ALLOWLIST`/`DENY_BY_RULE`. New `test_apply_deny_rules_preserves_an_existing_denial` pins it. |
| **4 LOW** rule-denial tool text wrong | **CLOSED** | `agent_loop.py:1355-1358` emits `"denied: an operator permission rule forbids this capability"` for rule denials. |
| **5 LOW** `rule_id` never persisted | **CLOSED** | `_record_policy_verdict` gained `rule_id` (`agent_loop.py:1489`, payload `:1502`); both integration tests assert `rule_id == "rule-1"`. |
| **6 LOW** test gaps (pending path / post-construction rule / store tenant isolation / tautology) | **CLOSED with residual INFO** | Pending-path test, `test_store_is_tenant_scoped`, and `test_apply_deny_rules_preserves_an_existing_denial` added. The allow-guard test (`:168`) remains structurally restricted-to-deny, but the two integration tests now carry behavioural `rule_id` assertions. |
| **7 INFO** `kind` not round-tripped | **OPEN (INFO, accepted)** | Unchanged; DENY-only default, fail-safe. Not required. |
| **8 INFO** `save()` INSERT-only | **OPEN (INFO, accepted)** | Unchanged. Not required. |

## 3. Adversarial boundary re-verification

- **(a) pending path fails closed + durable**: PASS for `APPROVE` (raises before dispatch; durable
  verdict recorded). See NEW-1 for `REJECT`.
- **(b) SELFDEV wired**: PASS — `responsibility_surface.py:629-635`; the same builder also
  routes `current.approval` through `resume_pending_approval`, so the new deny check applies
  there too.
- **(c) no rule path can ALLOW / auto-approve tier-3 / pre-empt C7**: PASS. Probe over all
  `ACTION_RISK_TIERS` + unknown capability × 3 modes with a `*` rule → **0 allow-outcomes**
  (`allow-leaks: []`); `PermissionRuleKind` == `["DENY"]`. `apply_deny_rules` can only return
  the original object or `DENY_BY_RULE`; C7 is still validated on resume.
- **(d) frozen matrix unchanged**: PASS. `evaluate_permission_gate` body byte-identical; the
  only `permission_gate.py` hunk is the additive early-return inside `apply_deny_rules`.
  `tests/product/test_permission_mode_matrix.py` is untouched by this commit.
- **(e) empty `deny_rules` byte-identical**: PASS for the *decision object* — runtime probe
  over 8 capabilities × 3 modes returned the identity object every time
  (`empty-identity-all: True`). Caveat: the `POLICY_VERDICT_RECORDED` payload now always
  carries an extra `rule_id: null` key (NEW-3).
- **(f) tests genuine**: PASS — simulated revert (monkeypatch `agent_loop.apply_deny_rules`→
  identity and `agent_loop.active_deny_rule`→None) makes **both** new integration tests fail
  (`2 failed, 9 deselected`).

## 4. Test runs (exact)

Requested command:

```
uv run --extra product-test pytest tests/product/test_permission_deny_rules.py \
  tests/product/test_permission_mode_matrix.py tests/product/test_terminal_chat_loop.py -q
```

→ **53 passed in 3.59s**. Per-file:

- `test_permission_deny_rules.py` → **11 passed** (was 8 pre-fix)
- `test_permission_mode_matrix.py` → **7 passed** (frozen matrix)
- `test_terminal_chat_loop.py` → **35 passed**

Bypass-detection revert probe → `2 failed, 9 deselected`.

## 5. New findings

1. **[MEDIUM — over-broad fail-closed; approval deadlock]** The deny check in
   `resume_pending_approval` runs *before* the disposition branch, so it blocks **REJECT** as
   well as APPROVE. Probe (real store, tier-3 `workspace.shell`, rule added post-escalation):

   ```
   REJECT raised: RunExecutionError denied by an operator permission rule: pending action is blocked
   ```

   Consequence: with a `*` wildcard rule active, a pending approval can be neither approved nor
   rejected; the continuation never resolves and the session is wedged until the operator
   revokes the rule. This is an availability/liveness regression in the approval workflow
   (prior behaviour recorded the rejection at `agent_loop.py:655-668`), not a fail-open. Fix:
   apply the rule denial only for `disposition is APPROVE`, or resolve REJECT normally; add a
   test for the REJECT-under-rule ordering.

2. **[LOW — ordering shadows reconciliation]** The deny check (`:541`) precedes the
   `_unknown_session_action` check (`:561`). If a pending action is in an unknown-effect state
   and a matching rule exists, the caller now gets `RunExecutionError` instead of
   `unknown_requires_review`, obscuring the external-reconciliation requirement. Fails closed,
   but the recovery signal is lost. Consider checking `unknown` first.

3. **[LOW / INFO — durable schema change]** `_record_policy_verdict` now emits `rule_id`
   (null for ALLOW / out-of-allowlist) on **every** `POLICY_VERDICT_RECORDED`, so pre-existing
   verdict events gain a key. Additive and non-secret; no existing test breaks, but it is not
   "byte-identical" at the event level. Downstream readers should tolerate the null key.

4. **[LOW — test gap]** SELFDEV deny wiring has no asserting test (finding 2 residual). Also
   no test pins REJECT-vs-rule ordering (NEW-1). Note: local imports inside
   `test_deny_rule_blocks_resolving_a_pending_approval` (`:315-316`) are stylistic only.

## 6. Verdict

**APPROVE_WITH_CHANGES**

The two required MEDIUM findings are substantially resolved: the pending-approval path now
fails closed with a durable, rule-attributed verdict and is provably bypass-detecting; SELFDEV
is wired; the wildcard-relabel, tool-text, and `rule_id`-persistence items are fixed; the
frozen matrix and empty-rule decision identity are preserved. Required before promotion:

1. Fix NEW-1 (deny rule must not block the safe REJECT disposition) and add a REJECT test.
2. Add a SELFDEV deny-rule test (or explicitly scope the claim to chat paths).
3. Optionally reorder the `unknown` check (NEW-2) and document the additive `rule_id`
   event key (NEW-3).

Per §0 this re-review is **not independent**; an independent model/human must confirm before
promotion/push/merge.
