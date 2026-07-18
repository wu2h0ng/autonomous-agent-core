# Verification — P-OUTCOME-PORTFOLIO-HELP-RESPOND-1

## Command

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:apps/api_server/src:. \
  python3 -m pytest \
  tests/product/test_mandate_outcome_portfolio.py \
  tests/product/test_mandate_outcome_portfolio_help_api.py \
  -q
```

## Result

20 passed.

## Surface

- `OutcomePortfolioHelpRespondCommand` + optional `OutcomePortfolioHelpRequest.response`
- `respond_help_request` (admin; OPERATOR_DECISION/CANCELLATION only; CAPABILITY_GRANT/REVOCATION fail closed)
- settle auto-cancels open Help for matching `task_id`
- list/view default open-only; `include_resolved=true` on list
- `POST /v1/mandates/{id}/outcome-portfolio/help-requests/{help_request_id}:respond`

## Claim ceiling

No TaskActivation / capability / effects / release / autonomy.
