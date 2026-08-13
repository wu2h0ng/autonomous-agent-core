# Brief — P-OUTCOME-PORTFOLIO-HELP-RESPOND-1

Track: Product. Class: U/P/A (primary P; A for fail-closed authority).
Base: Agent OS `origin/main` @ `972ecae` (code head includes Help HTTP `e908c26`).

## Named U
Operator can close or decide an Outcome-Portfolio gap HelpRequest without re-deriving state from chat, and successful settlement clears matching open Help noise.

## Scope (must ship together)
1. Persist typed `SrlHelpResponse` against an open `OutcomePortfolioHelpRequest` (admin-only).
2. Allowed kinds on this path: `OPERATOR_DECISION` and `CANCELLATION` only.
3. `CAPABILITY_GRANT` and `REVOCATION_REQUEST` **must fail closed** here (no authority laundering).
4. On successful `settle(...)`, auto-append `CANCELLATION` responses for open HelpRequests whose `task_id` matches the settled commitment (and/or gap kinds that the settle cured: MISSING_OBSERVED_OUTCOME when VERIFIED/NOT_MET settlement lands).
5. List/view: default list open-only; admin may filter `include_resolved=true`.
6. HTTP: `POST /v1/mandates/{id}/outcome-portfolio/help-requests/{help_request_id}:respond` with body = SrlHelpResponse fields (server binds responder principal).
7. Keep `authority_granted` / activation / capability / effects literal `False`.

## Out of scope
- UI/Agent Surface
- B4 / Nonoracle / research freeze
- Release, SPINE-1, provider dispatch, TaskActivation
- New Help taxonomy (reuse `SrlHelpResponse`)

## Tests (RED first)
- Admin OPERATOR_DECISION APPROVE/REJECT/MORE_INFO persists; non-admin denied
- CAPABILITY_GRANT via respond path denied
- CANCELLATION closes request; subsequent list excludes it unless include_resolved
- Successful settle auto-cancels matching open gap Help
- HTTP respond route admin-only; response does not grant activation/capability/effects

## Done when
Focused product tests green; commit+push feature branch; write verification.md with commands+results. No merge (controller merges after independent review).
