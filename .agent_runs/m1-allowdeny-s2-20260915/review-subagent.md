# Independent adversarial exact-diff review — S2 DURABLE OPERATOR DENY-ONLY RULES

> Reviewer: subagent (adversarial, exact-diff)
> Model: deepseek-flash
> Builder: wu2h0ng; builder model recorded as deepseek-flash in prior rounds ← SAME MODEL; see §0
> Worktree: `autonomous-agent-core/.worktrees/m1-danger-cmd-20260915`
> Commit under review: `f8a8a324` (parent `8a291279`; base `origin/main` `18d7b9b0`)
> Gate doc: `.agent_runs/m1-allowdeny-s2-20260915/goal-card-cp-ab.md`
> Scope of write: this file only; all source/test files were treated READ-ONLY.

## 0. Independence limitation (must be recorded)

Root `AGENTS.md` §11 requires `builder_id != reviewed_by`. I am the **same model** as the
builder (deepseek-flash), as were all prior S1 rounds. This review is therefore **not** an
independent sign-off and cannot, by itself, satisfy the independent exact-diff gate. A
different model or a human must confirm this verdict before promotion/push.

## 1. Exact revision binding

`git show --stat f8a8a324` and `git diff 8a291279..f8a8a324` were read. The commit is 8
files, +735 / −5:

- `.agent_runs/m1-allowdeny-s2-20260915/goal-card-cp-ab.md` (new gate doc)
- `.agent_runs/m1-danger-cmd-20260915/review-subagent-final.md` (prior S1 round, committed)
- `apps/api_server/app.py` (composition-root store + 2 loop wiring sites)
- `packages/os_core/src/agent_os_core/__init__.py` (exports)
- `packages/os_core/src/agent_os_core/agent_loop.py` (optional `deny_rules`, gate post-step)
- `packages/os_core/src/agent_os_core/permission_gate.py` (new outcome/basis/field + `apply_deny_rules`)
- `packages/os_core/src/agent_os_core/permission_rules.py` (new)
- `tests/product/test_permission_deny_rules.py` (new, 8 tests)

Files read directly and in full: `permission_gate.py`, `permission_rules.py`,
`agent_loop.py` (`_execute_proposal`, `resume_pending_approval`, `_record_policy_verdict`,
`_record_out_of_allowlist_denial`), `app.py` (`open_chat_session`, `restore_chat_session`,
`surface_begin_turn`, `decide_session_approval`), `responsibility_surface.py:560-640`,
`tests/product/test_permission_deny_rules.py`, `tests/product/test_permission_mode_matrix.py`.

## 2. Verification against the requested checklist

| # | Check | Result |
|---|---|---|
| a | Any rule path ever ALLOW / auto-approve tier-3 | **PASS** — `apply_deny_rules` returns only the *original decision object* or `DENY_BY_RULE`; no branch can raise `risk_tier` or emit `TIER_DEFAULT_AUTO_PASS`/`MODE_AUTO_ALLOW`/`REQUIRE_CONFIRM`. Runtime matrix probe (all `ACTION_RISK_TIERS` + unknown × 3 modes, wildcard rule) produced **0 anomalies**; `PermissionRuleKind` has only `DENY`; `kind="ALLOW"` is rejected by pydantic `ValidationError`. |
| b | Rule bypass/alter C7 or correction authority | **PASS** — the layer only short-circuits dispatch; it touches no C7/`op_*`/audit/promotion surface. C7 is still validated on resume (`_validate_pending_runtime(..., require_current_c7=...)`, `agent_loop.py:574-578`). Wildcard can *prevent carrying out* a corrective action but cannot override/clear C7 (see INFO F7). |
| c | Frozen `evaluate_permission_gate` truly unchanged (semantics) | **PASS** — line-level diff vs `8a291279` shows only additive lines (import, enum member, `basis` literal widened, new `rule_id` field, new function *after* line 83). The function body 51-83 is byte-identical. |
| d | Revocation durable/effective; scope enforced; wildcard safe | **PASS with caveat** — store revoke/reopen test proves durability; scope is double-enforced (`list_active` SQL filter + `active_deny_rule` tenant/workspace compare); wildcard `*` is still scope-bounded. Caveat: rules are snapshotted at loop construction and are only effective at the next loop build (each turn rebuilds the loop → fine per-turn), and are **not** consulted on the pending-approval resume path (F1). |
| e | `deny_rules` default `()` byte-identical | **PASS** — with `()` the layer returns the same decision by identity; the deny branch fires only for `DENY_OUT_OF_ALLOWLIST`; `basis`/`reason` strings are unchanged for the non-rule path. Only extra effect is one no-op call. |
| f | `PermissionGateDecision.rule_id` leak | **PASS** — `rule_id` is set only on `DENY_BY_RULE` and is **never** serialized: `_record_policy_verdict` does not accept/emit it, `_tool_message` does not include it; repo-wide grep for `rule_id` matches unrelated history-safety/SPINE-1 code only. It is under-recorded, not leaked (F5). |

## 3. Adversarial boundary probes (author-run, verbatim results)

```
anomalies: []
kind ALLOW rejected: ValidationError
scope-mismatch identity: True
```

- Empty rules → identity object for every capability×mode (`apply_deny_rules(...) is d`).
- Wildcard rule → `DENY_BY_RULE` for every capability×mode, never in the allow set.
- Cross-scope rule (`tenant_id="other"`) → identity (no-op).
- `kind="ALLOW"` cannot be constructed.

Pending-approval probe:

```
resume_pending_approval consults deny_rules: False
resume_pending_approval consults gate: False
```

## 4. Is the integration test real? (bypass detection)

Runtime probe: monkeypatched `agent_os_core.agent_loop.apply_deny_rules` to the identity
function (simulating "rule layer absent") and executed
`test_deny_rule_blocks_a_mode_auto_allowed_edit`:

```
EXPECTED_FAIL (bypass detected): expected a DENY-by-rule policy verdict
```

So the test genuinely fails if the rule is not consulted — it is bypass-detecting, not a
constant-return shell. (The commit's own comment "Add the rule BEFORE the session loop is
built" is slightly inaccurate — `surface_begin_turn` rebuilds the loop via
`restore_chat_session`, so a later-added rule would also be picked up — but harmless.)

## 5. Test runs (exact)

- `uv run --extra product-test pytest tests/product/test_permission_deny_rules.py tests/product/test_permission_mode_matrix.py -q`
  → **15 passed in 0.83s** (8 deny-rules + 7 frozen-matrix)
- `… test_permission_deny_rules.py -q` → **8 passed in 0.41s**
- `… test_permission_mode_matrix.py -q` → **7 passed in 2.03s**
- `… test_terminal_chat_loop.py test_permission_mode_matrix.py test_permission_deny_rules.py -q`
  → **50 passed in 3.37s**
- `git diff --check 8a291279..f8a8a324` → clean (exit 0)

Full `tests/product` baseline was **not** re-run (the 23-failed-==-base claim is unverified
here); no regression observed in the adjacent suites exercised.

## 6. Findings (severity-ranked)

1. **[MEDIUM — boundary gap / fail-open] DENY rules are not enforced on the pending-approval
   resume path.** `resume_pending_approval` (`agent_loop.py:493+`) never calls
   `evaluate_permission_gate` or `apply_deny_rules`; it goes straight to C7 validation and
   dispatch. `restore_chat_session` *does* fetch the active rules into the loop
   (`app.py:2095`), so they are silently ignored on this path. Consequence: an action already
   in `REQUIRE_CONFIRM`/pending can still execute after a matching operator DENY rule is
   created (e.g. tier-3 `workspace.shell`). This is fail-open with respect to the new
   restriction and contradicts the "durable operator DENY rules" framing. Required change:
   either (i) enforce — a matching unrevoked rule forces the pending approval to be denied/
   rejected (preferred, keeps "purely restrictive, fail-closed"), or (ii) obtain an explicit
   founder decision to scope deny rules to proposal-time only and add a negative test pinning
   that ordering. **No such test exists today.**

2. **[MEDIUM — coverage/claim accuracy] The SELFDEV execution path ignores deny rules.**
   `responsibility_surface.py:599` constructs an `AgentLoop` without `deny_rules`, on a live
   path with `independent_approval=True, external_exact_approval=True`. The gate doc discloses
   this in §5, but the delivered claim ("durable, operator-authored DENY-only permission
   rules") is unconditional. Required change: a founder decision to either wire `deny_rules`
   into that builder or formally scope S2 to chat paths, plus a test asserting the chosen
   behavior. Because SELFDEV is the higher-consequence path, wiring is preferred.

3. **[LOW — audit semantics] A wildcard rule rewrites genuine out-of-allowlist denials.**
   When the frozen gate returns `DENY_OUT_OF_ALLOWLIST` for an unknown/sandbox-escape
   capability and *any* `*` rule is active, `apply_deny_rules` downgrades it to
   `DENY_BY_RULE`/`basis="rule"`, masking the sandbox-escape semantics in
   `POLICY_VERDICT_RECORDED`. Recommend applying the rule downgrade only when the gate
   outcome is not already `DENY_OUT_OF_ALLOWLIST` (or record both bases).

4. **[LOW — misleading model feedback] The rule-denial tool message is wrong.**
   `agent_loop.py:1331-1337` returns `"denied: capability is outside the allowlist"` for a
   rule denial. The durable verdict reason is correct, but the model is told the wrong thing
   and may retry a different capability. Recommend a rule-specific message.

5. **[LOW — under-recorded audit] `rule_id` is available but never persisted.**
   `PermissionGateDecision.rule_id` is populated (`permission_gate.py:108`) yet
   `_record_policy_verdict` (`agent_loop.py:1455`) emits no `rule_id`. No leak (verified), but
   the audit cannot attribute the denial to the exact rule. Recommend adding `rule_id` to the
   verdict payload (non-secret field).

6. **[LOW — test gaps]**
   - No test of the pending-approval path (finding 1).
   - No test that a rule created *after* loop construction is picked up on the next turn.
   - Store-level tenant isolation is only tested via `active_deny_rule`, not via
     `SQLitePermissionRuleStore.list_active` with mixed-tenant rows.
   - `test_apply_deny_rules_never_produces_an_allow_outcome` is structurally tautological (by
     construction the function can only return unchanged-or-deny), so on its own it cannot
     detect a future ALLOW path; keep it, but add a behavioral allow-path guard on the
     `AgentLoop` side.

7. **[INFO] `PermissionDenyRule.kind` is not round-tripped.** The table has no `kind` column
   and `_row_to_rule` omits it (defaults to `DENY`). Fail-safe today (DENY is the only and
   safe default), but a future non-DENY kind would be silently coerced. Consider persisting
   it or asserting `DENY` on load. A wildcard rule could also prevent the agent from *acting
   on* a correction (it cannot override C7) — acceptable as an operator choice, noted for
   completeness.

8. **[INFO] `save()` is INSERT-only** (no upsert); re-saving an existing `rule_id` raises a
   raw `sqlite3.IntegrityError`. Minor robustness; not a boundary issue.

No HIGH findings. The DENY-only boundary itself is sound: no rule path can allow, auto-approve
tier-3, or override C7; the frozen E2 matrix is genuinely unchanged; empty `deny_rules` is
byte-identical. The two MEDIUM items are about *restriction coverage/claim scope*, not about
introducing a grant.

## 7. Verdict

**APPROVE_WITH_CHANGES**

Required changes before promotion:
1. Resolve finding 1 (enforce deny rules on `resume_pending_approval`, or get an explicit
   founder-scoped exemption) and add the corresponding test.
2. Resolve finding 2 (wire `deny_rules` into `responsibility_surface.py`, or formally scope
   S2 to chat paths with a test).
3. Record `rule_id` in the policy-verdict payload and fix the rule-denial tool message
   (findings 4–5); guard the out-of-allowlist basis against wildcard masking (finding 3).

Per §0 this review is **not independent** (same model as builder); an independent
model/human must confirm before promotion/push/merge.
