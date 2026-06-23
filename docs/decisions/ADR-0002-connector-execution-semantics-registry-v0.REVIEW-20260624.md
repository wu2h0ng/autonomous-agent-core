# ADR-0002 Connector Execution Semantics Registry v0 — Review

Date: 2026-06-24
Branch: `codex/durable-action-ledger`
Reviewed commit: `1aade89 Add connector execution semantics registry`

## Findings

1. **Gate-state drift — fixed.**
   `ADR-0002-governed-action-outcome-loop-v0.SPEC.md` and the ADR footer described the
   implementation as local `main`. That was wrong: the implementation is on local feature
   branch `codex/durable-action-ledger` and remains unmerged. The text now says the branch is
   not merged to `main` and still requires AR-20260624 CTO gate acceptance plus founder
   merge/push/release authorization.

2. **Verification-count drift — fixed.**
   The older ADR-0002 remediation verification file still records the historical 404-test
   run. That record is preserved as historical evidence, with a freshness note pointing to
   `docs/CURRENT_STATE.yaml` and the connector execution-audit verification record for the
   current 414-test live count.

3. **Product/process boundary wording — fixed.**
   README and AGENTS mixed OpenAPI/observability CI gates into product capability language.
   Runtime capabilities now stay in the delivered-capabilities section, while OpenAPI drift,
   observability gate tests, ruff/format, unittest/eval, and PostgreSQL parity are listed as
   engineering verification gates.

## Runtime / Security Review

No blocking runtime or API-safety finding was found in local review:

- `ConnectorExecutionSemantics` is a connector-contract default, not proof of external
  success.
- `TrustedLoopRuntime` fills audit defaults from the registered connector contract using
  `setdefault`, so explicitly reported safe connector fields remain visible without copying
  raw payloads.
- `ConnectorExecutionAudit` projects only whitelisted fields and excludes raw parameters,
  secret-like fields, and raw connector payloads.
- `external_ack_status` still defaults to `unknown` for external connector semantics unless
  a connector explicitly reports otherwise.
- The branch continues to deny external-system exactly-once, external ACK confirmation,
  durable arbitrary external connector recovery, and automatic R4/R5 execution.

Two parallel read-only explorer attempts for runtime/security review failed at tool layer with
`Unsupported content type`; their failures are not counted as review approval. A separate
governance/documentation explorer completed and supplied the drift findings above.

## Approval Status

Review result: **documentation drift remediated; no new release/merge approval granted**.

Remaining gate: `codex/durable-action-ledger` still must not merge or release until
AR-20260624 CTO gate acceptance and founder merge/push/release authorization.
