# Next Product Lane Brief — P-OUTCOME-PORTFOLIO-HELP-1

Status: READY_TO_DISPATCH
Base: Agent OS origin/main `4f7db2a`
Track: Product 35%
Claim ceiling: no activation / capability / effects / release

## U
When settlement cannot proceed (missing ObservedOutcome, revoked MandateTaskLink, digest drift),
operator receives a structured HelpRequest instead of silent failure or chat discovery.

## P (minimal)
- Emit typed HelpRequest from Outcome Portfolio attach/settle denial paths that are information/authority gaps
- Persist HelpRequest bound to mandate_id + portfolio_id + task_id (if any)
- GET surface to list open HelpRequests for mandate (admin)
- Do NOT auto-create tasks, grant capabilities, or call providers

## Stop
No TaskActivation; no W3/W4; no SPINE-1; no Alpha claim.

## Tests (RED first)
- settle without ObservedOutcome → HelpRequest (not only Denied)
- settle after link revoke → HelpRequest
- HelpRequest cannot authorize activation flags
