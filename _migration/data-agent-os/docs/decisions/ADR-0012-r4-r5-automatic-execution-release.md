# ADR-0012: Configurable R4/R5 Automatic Execution Capability

- Status: **Accepted — implementation authorized via ADR-0013 concurrent roadmap**
- Date: 2026-07-07
- Authorization claim: founder/CTO level, scope = add tenant-configurable R4/R5 automatic execution capability
- Supersedes/revises: relevant R4/R5 prohibition clauses in ADR-0002, ADR-0005, AGENTS.md §Hard Boundaries 5, and CURRENT_STATE.yaml line 1
- Risk class: R5 (capability for automatic high-risk business side-effects; default remains proposal-only)

## 1. Context

Project baseline treated R4/R5 automatic execution as out-of-bounds for MVP:

- `AGENTS.md` Hard Boundary 5: "R4/R5 business actions are proposal-only in MVP."
- `ADR-0002-governed-action-outcome-loop-v0.md` boundary #4: "不做 R4/R5 自动执行" and "R4/R5 `action_proposal` tools can produce proposals without executing the business action."
- `ADR-0005-full-os-architecture-is-staged-target.md`: "R4/R5 actions remain proposal-only until OperationContract, PolicyDecision, ApprovalDecision, rollback/compensation, and OperationTrace are implemented and approved."
- `docs/CURRENT_STATE.yaml` line 1: "R4/R5 automatic execution remains unauthorized."

MVP is now complete. The next engineering phase is to add a **configurable** capability that lets tenants decide whether and when R4/R5 actions may execute automatically. The platform provides the mechanism and guardrails; the tenant policy decides whether to use it.

## 2. Decision

**Add tenant-configurable automatic execution capability for R4/R5 business actions.**

### 2.1 Default behavior

- **Out-of-the-box default for all tenants: R4/R5 remain proposal-only and require human approval.**
- No tenant can accidentally trigger automatic R4/R5 execution.
- Existing MVP behavior is unchanged unless a tenant explicitly opts in via policy.

### 2.2 Tenant policy controls enablement

A tenant administrator or authorized policy owner may configure an `AutoExecutionPolicy` that overrides the default for specific action types, domains, risk levels, and guard conditions.

The policy is the authoritative decision surface:

- **Policy denies / not configured** → R4/R5 action is proposal-only.
- **Policy pre-approves with guard conditions** → R4/R5 action may execute automatically when all conditions are met.
- **Policy may allow R5 automatic execution** if the action declares a compensating action or escalation path.

### 2.3 What R4/R5 means

Risk classification in this project:

- **R0-R1**: read-only, no side-effects.
- **R2-R3**: reversible or low-impact writes; may be auto-executed under policy today.
- **R4**: high-impact business writes with material P&L or operational consequences (e.g., budget adjustments, inventory movements, price changes, campaign status changes).
- **R5**: highest-risk writes with irreversible or regulated consequences (e.g., financial postings, contract changes, customer data mutations, safety-critical operations).

### 2.4 Scope of capability

- Applies to all `OperationContract`-covered actions.
- Applies to R4 and R5.
- Applies across all domains, because the capability is in OS Core; domain packs supply the action templates and risk metadata.

## 3. Preconditions (must all pass before implementation PR)

No code enabling R4/R5 automatic execution may land until the following are implemented and reviewed:

### 3.1 Policy Engine

A real `PolicyEngine` must evaluate each R4/R5 action against:

- Tenant-level `AutoExecutionPolicy`.
- Per-action `OperationContract.risk_policy`.
- Principal/scope of the invoking identity.
- Required guardrails: dry-run success, confidence floor, evidence completeness, metric delta bounds, time windows, spend limits, etc.

### 3.2 Approval Decision Record

Automatic execution is **not** zero-approval. It is **policy pre-approval**:

- A durable `ApprovalDecision` or `PolicyApprovalRecord` must be generated before execution.
- The record must bind to a specific `ActionProposal`, `OperationContract`, evidence chain, and policy rule.
- The record must be auditable and revocable.
- A revoked policy must immediately block future automatic executions.

### 3.3 Rollback / Compensation

- R4 actions must have a snapshot/rollback path or a documented compensating action.
- R5 actions must declare a compensating action or human escalation path in `OperationContract`.
- Runtime must refuse automatic execution if rollback/compensation is missing for the configured risk level.

### 3.4 OperationTrace Coverage

Every automatically executed R4/R5 action must produce:

- `OperationTrace` with `proposed -> policy_evaluated -> policy_pre_approved -> executed -> observed` states.
- Tamper-evident trace events.
- Fingerprint-bound context for resume/replay.
- Policy rule reference and policy owner identity.

### 3.5 Corrigibility (C7) Still Supreme

A paused shell (`ShellView.paused`) must block **any** automatic R4/R5 execution at the runtime level, regardless of tenant policy. This is non-negotiable.

### 3.6 Eval and Negative Paths

Red-first eval must cover:

- R4/R5 default to proposal-only when no policy is configured.
- R4/R5 blocked when policy denies.
- R4/R5 blocked when shell is paused.
- R4/R5 blocked when evidence chain is incomplete.
- R4/R5 blocked when dry-run fails.
- R4/R5 blocked when policy approval record is missing or revoked.
- R4/R5 blocked when rollback/compensation is missing.
- Rollback/compensation restores pre-action state or triggers correct escalation.
- Duplicate idempotency keys do not double-execute.
- Policy change after proposal but before execution blocks stale automatic execution.

### 3.7 Contract / OpenAPI Updates

- `OperationContract` must expose:
  - `auto_executable: bool = False`
  - `required_policy_guardrails`
  - `compensating_action` (required for R5)
- `AutoExecutionPolicy` contract must be defined.
- `ActionProposal` must expose `execution_mode: proposal_only | policy_pre_approved`.
- OpenAPI snapshot must be regenerated and drift gate must pass.

### 3.8 UI / Management Surface

- Tenant admin must be able to view and edit `AutoExecutionPolicy`.
- UI must clearly distinguish automatic vs human-approved executions.
- UI must show policy owner and audit trail.

### 3.9 Documentation Updates

- `AGENTS.md` Hard Boundary 5 must be revised.
- `docs/CURRENT_STATE.yaml` must be updated.
- This ADR must move from **Draft** to **Accepted**.

## 4. Policy Configuration Contract (illustrative)

```yaml
auto_execution_policy:
  version: "1"
  tenant_id: "t_001"
  owner: "admin@example.com"
  default_mode: proposal_only
  rules:
    - rule_id: "campaign-budget-r4"
      action_type: "adjust_campaign_budget"
      risk_levels: ["R4"]
      mode: policy_pre_approved
      guard_conditions:
        dry_run_required: true
        dry_run_success: true
        evidence_complete: true
        confidence_min: 0.9
        max_delta_pct: 5
        max_daily_spend_delta_cny: 10000
        allowed_time_window: "09:00-18:00"
      compensating_action: "restore_campaign_budget"

    - rule_id: "financial-voucher-r5"
      action_type: "create_financial_voucher"
      risk_levels: ["R5"]
      mode: policy_pre_approved
      guard_conditions:
        evidence_complete: true
        confidence_min: 0.99
        require_secondary_approval: false
      compensating_action: "reverse_voucher_and_notify_finance"
```

## 5. Safety Architecture

```text
BusinessIntent
  -> EvidenceChain (complete)
  -> ActionProposal (R4/R5 flagged)
  -> PolicyEngine.evaluate(tenant_policy, proposal, evidence, principal)
     -> DENY / NOT_CONFIGURED: proposal-only, route to human approval
     -> CONDITIONAL: require human approval
     -> POLICY_PRE_APPROVED: generate durable PolicyApprovalRecord
  -> RuntimePolicyGate (re-check pause shell, risk ceiling, policy record validity)
  -> dry-run / snapshot (R4) or compensating-action validation (R5)
  -> connector.execute()
  -> OperationTrace.record(policy_rule_id, policy_owner)
  -> Feedback / Outcome capture
```

## 6. Boundaries / Non-Goals

- **No default-on behavior.** R4/R5 automatic execution is opt-in per tenant policy.
- **No platform-imposed blanket permission.** The platform decides whether a configuration is structurally valid; the tenant decides whether to enable it.
- **No removal of human accountability.** Owner, policy rule, trace, and audit remain structurally present.
- **No autonomous goal-setting.** The system executes pre-registered actions within policy; it does not invent business objectives.
- **No cross-repo import of `autonomous-agent-core`.** Hard Boundary #19 remains in force.
- **No weakening of SQL Safety or EvidenceChain.** Grounding invariant (P5.1b-ii) remains.
- **No claim of full autonomy.** Marketing and external narrative must still avoid "autonomous AI" language.

## 7. Responsibility Model

| Layer | Responsibility |
|---|---|
| Platform | Provide PolicyEngine, guardrails, trace, audit, rollback/compensation enforcement, safe defaults. |
| Tenant / Policy Owner | Decide whether to enable automatic execution, for which actions, under which conditions. |
| Action Connector | Declare risk level, execution semantics, rollback/compensation capabilities. |
| Operator | Can pause the entire system (C7) regardless of tenant policy. |
| Auditor | Review OperationTrace and PolicyApprovalRecord after the fact. |

## 8. Implementation Gate

Before marking implementation complete, the completion gate must state:

- The real entry point that invokes R4/R5 auto-execution.
- The `AutoExecutionPolicy` / `OperationContract` / `PolicyApprovalRecord` schemas consumed and produced.
- The negative paths covered by tests (especially default-off behavior).
- The regression test that fails if auto-execution is enabled by default or bypassed.
- The reason OS Core boundaries remain intact.
- Whether OpenAPI changed (snapshot regenerated + drift gate passed).
- Whether observability trace steps and telemetry dimensions are updated.

## 9. Rollback Plan

If the capability causes incidents or trust regression:

1. Revert the implementation PR.
2. Restore `OperationContract.auto_executable` defaults to `false`.
3. Invalidate any in-flight `PolicyApprovalRecord` that has not yet executed.
4. Update `CURRENT_STATE.yaml` to note the reversion.
5. Run a post-mortem and require a revised ADR before re-enabling.

## 10. Approval

- Approved by: founder/CTO
- Date: 2026-07-07
- Scope confirmed: tenant-configurable R4/R5 automatic execution capability, default proposal-only

---

*R4/R5 automatic execution capability is authorized for implementation. The default remains proposal-only; tenants must explicitly opt in via `AutoExecutionPolicy` after all preconditions are met.*
