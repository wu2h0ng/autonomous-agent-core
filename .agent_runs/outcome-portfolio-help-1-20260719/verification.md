# Verification: P-OUTCOME-PORTFOLIO-HELP-1

Date: 2026-07-19
Branch: codex/outcome-portfolio-help-1-20260719
Base: origin/main 4f7db2a
Track: Product 35%

## Tests

```
11 passed in 0.44s

test_portfolio_contract_rejects_activation_true PASSED
test_only_same_scope_admin_can_create_portfolio PASSED
test_attach_rejects_task_without_active_mandate_link PASSED
test_create_attach_and_settle_not_met PASSED
test_invalid_outcome_cannot_settle_met PASSED
test_help_request_rejects_activation_flags PASSED
test_settle_without_observed_outcome_emits_help_request PASSED
test_settle_after_link_revoke_emits_help_request PASSED
test_list_help_requests_requires_admin PASSED
test_get_view_includes_help_requests PASSED
test_attach_commitment_without_link_emits_help_request PASSED
```

Neighboring regression: all 50 tests pass (portfolio, responsibility, observation_authorization, workspace_api).

## Contract

- `OutcomePortfolioHelpGap` enum: MISSING_OBSERVED_OUTCOME, MISSING_TASK_LINK, REVOKED_TASK_LINK, DIGEST_DRIFT, CORRECTION_EPOCH_DRIFT, MISSING_COMMITMENT_OR_EXPECTED, SCOPE_MISMATCH
- `OutcomePortfolioHelpRequest`: typed help bound to mandate_id + portfolio_id + task_id (optional); all authority/activation flags fixed to Literal[False]
- `OutcomePortfolioView.help_requests`: included in view alongside portfolio/commitments/settlements
- `_outcome_portfolio_help_request_id()`: deterministic content-based id

## Implementation

- `SQLiteMandateOutcomePortfolioStore`:
  - `_HELP_TABLE`: durable persistence of help requests
  - `_require_active_task_link()`: accepts deferred help collection; emits help for missing/revoked link, epoch drift, digest drift
  - `attach_commitment()`: emits help for missing commitment/expected, digest drift, scope mismatch
  - `settle()`: emits help for missing ObservedOutcome, expected/observed digest drift, observed status mismatch
  - `_flush_help_deferred()`: flushes collected help after transaction rollback (avoids SQLite write-lock conflict)
  - `list_help_requests()`: admin-only GET surface bound to mandate scope
- No auto-create tasks, no capability grants, no provider calls, no release

## Claims

- `task_activation_authorized` stays False in HelpRequest contract
- `authority_granted` stays False in HelpRequest contract
- `capability_grant_authorized` stays False in HelpRequest contract
- `external_effects_authorized` stays False in HelpRequest contract
- No TaskActivation, no W3/W4, no SPINE-1, no Alpha claim

## Unsatisfied

- One pre-existing pyright error in `_require_active_task_link` (`active[0]` index) unchanged by this PR
- Test file pyright errors (content_digest on Optional model fields) are pre-existing patterns unchanged by this PR

## Taxonomy binding (post pre-review)

`OutcomePortfolioHelpRequest` is a portfolio binding envelope over canonical
`SrlHelpRequest` (`srl_help` field). `OutcomePortfolioHelpGap` maps into
`HelpClass` via `help_class_for_gap`; it is not a second help taxonomy.

