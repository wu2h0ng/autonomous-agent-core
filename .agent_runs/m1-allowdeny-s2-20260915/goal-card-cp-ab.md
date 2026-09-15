# Goal Card + CP/AB + GATE — S2 DURABLE PERMISSION DENY RULES

> Status: `FOUNDER_GATE_DENY_ONLY / IMPLEMENTED / PENDING_INDEPENDENT_EXACT_DIFF_REVIEW`
> Track: Product Track, medium/high risk (touches the permission path).
> Cast: P2-7 M1 route A, target Python core. Base `origin/main` @ `18d7b9b0`.
> Claim ceiling: no parity / autonomy / release claim.

## 1. Founder gate (2026-09-15)

Recon found the only effective seam is `permission_gate.evaluate_permission_gate`, the
**frozen E2 mode x tier x verdict matrix** — changing it is a governance change
(founder-reserved). The founder authorized the **DENY-only** subset: durable rules may
only *restrict*; there is no ALLOW rule kind, no tier-3 auto-approval, and C7 is
untouched. The frozen matrix function is unchanged.

## 2. What was implemented

- `permission_rules.py`: `PermissionRuleKind` (DENY only) · `PermissionDenyRule`
  (id, capability_id incl. `*`, tenant/workspace scope, created_by/at, reason,
  revoked_at) · `active_deny_rule()` · `rule_matches()` · `SQLitePermissionRuleStore`
  (save / durable revoke / list_active).
- `permission_gate.py`: new `PermissionGateOutcome.DENY_BY_RULE` + `basis="rule"` +
  `apply_deny_rules()` which downgrades ANY decision to DENY_BY_RULE on a match and is
  otherwise a no-op. The frozen `evaluate_permission_gate` is unchanged.
- `agent_loop.py`: optional `deny_rules` (default `()`), consulted immediately after the
  gate; a `DENY_BY_RULE` records `POLICY_VERDICT_RECORDED(DENY, basis="rule")` and the
  action is not executable/approvable — same fail-closed branch as out-of-allowlist.
- `apps/api_server/app.py`: composition-root `SQLitePermissionRuleStore` on the
  canonical DB; the two chat-loop builders pass the active rules.

## 3. Boundaries honoured

- A rule can never allow, auto-approve tier-3, or pre-empt C7 (`test_apply_deny_rules_
  never_produces_an_allow_outcome` iterates the whole matrix with a `*` rule).
- Default is empty rules → byte-identical prior behaviour.

## 4. Verification

- `tests/product/test_permission_deny_rules.py` (8): rule/no-ALLOW-kind, matching, scope,
  revocation, durable reopen, gate downgrade, no-op, never-allow, and an integration test
  driving the real chat path (ACCEPT_IN_WORKSPACE edit denied by rule).
- Adjacent permission suites (matrix, chat loop, trusted shell) 53 pass.
- Full `tests/product` 23 failed == base (env/date + flaky), zero new.
- Ruff clean; pyright 0 on changed files.

## 5. Residual / honesty

- Residual: `responsibility_surface.py` builds its own AgentLoop and does not pass
  `deny_rules` (not a chat permission path); noted, not wired.
- Independent exact-diff review still required before promotion.
