# GC + CP/AB + GATE REQUEST — S2 ALLOW/DENY RULE PERSISTENCE

> Status: `DESIGN_ONLY / NOT_AUTHORIZED / GOVERNANCE_GATE_REQUIRED`
> Track: Product Track, **medium/high risk** (changes a frozen governance matrix).
> Cast: P2-7 M1 route A, target Python core. Base would be `origin/main`.
> Claim ceiling: no parity / autonomy / release claim.

## 1. Why this needs your gate

S2 implements the GAP-ANALYSIS item *"allow/deny 规则引擎（模式匹配 + 持久化）… 无 glob
模式规则、无 'don't ask again' 持久化"*. The only place a persisted allow-rule can take
effect is `packages/os_core/src/agent_os_core/permission_gate.py`, whose docstring is
explicit: it is the **frozen E2 mode x tier x verdict matrix**. Changing its behaviour is
a governance change, so per AGENTS.md §7 and the constitution this is founder-reserved:
I will not implement it without your route/gate.

## 2. Current behaviour (verified at origin/main 18d7b9b0)

`evaluate_permission_gate(capability_id, mode, mode_event_id)` returns one of:
- `TIER_DEFAULT_AUTO_PASS` (tier ≤ 1),
- `MODE_AUTO_ALLOW` (tier 2 AND `ACCEPT_IN_WORKSPACE`),
- `REQUIRE_CONFIRM` (tier ≥ 3, or tier 2 when not in that mode),
- `DENY_OUT_OF_ALLOWLIST` (capability not in `ACTION_RISK_TIERS`).

The matrix is frozen and has **no persistence**; every session re-evaluates from the mode.
`PermissionMode = ASK | ACCEPT_READ_ONLY | ACCEPT_IN_WORKSPACE`.

## 3. The hard boundary (non-negotiable)

- C7 stays non-writable/non-bypassable: a persisted rule must **never** convert a
  C7-blocked action into an allowed one, and must never pre-empt the correction authority.
- A persisted rule must never auto-approve **tier-3** (that is the whole point of the
  tier-3 human confirmation). "Don't ask again" for tier-3 is **out of scope**.
- Every rule write/read that changes a verdict must be a durable, auditable record.

## 4. Safe subset I propose (fail-closed first)

| Rule kind | Scope | Effect | Notes |
|---|---|---|---|
| DENY | capability_id (+ optional glob on the arguments) | forces `DENY_OUT_OF_ALLOWLIST`-equivalent | purely restrictive; safe |
| ALLOW | capability_id, **tier ≤ 2 only** | upgrades `REQUIRE_CONFIRM`→`MODE_AUTO_ALLOW` for that capability | must be operator-authored, scoped, audited |
| (never) ALLOW tier-3 | — | forbidden | tier-3 always requires a real ApprovalDecision |

- Storage: a new SQLite table (durable), reusing the E2 three-record chain for provenance:
  rule-authored / rule-consulted / rule-revoked. Operator-authored only; a model-proposed
  rule is a proposal, not a rule.
- Consultation order: DENY (most restrictive) → ALLOW(tier≤2) → existing frozen matrix.
  C7 is consulted by the caller as today and always wins.
- Revocation: durable; a revoked rule stops applying immediately.

## 5. Questions that decide the gate

1. Do you authorize changing the frozen E2 matrix at all (vs. keeping rules as a separate
   layer that only *restricts*, i.e. DENY-only)?
2. If ALLOW(tier≤2) is authorized: which scope (workspace / session) and what default
   (fail-closed)?
3. Is an ADR required before implementation, or is this GC + your route cast sufficient?

## 6. What I will NOT do without explicit approval

Implement any rule engine, alter `evaluate_permission_gate`, add the storage table, or
touch C7/approval semantics. This document authorizes nothing.
