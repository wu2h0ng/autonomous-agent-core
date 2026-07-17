# R-STATE-CREDIT-1 runnable successor F amendment

Status: `IMPLEMENTED_CANDIDATE / NOT_READY / NOT_FROZEN / NOT_RUN`

This additive successor preserves the independently reviewed mechanism base
`0ca38aa3491161fa115c0b58685cf408e5be106b`. It does not modify or reactivate
the historical recast candidate or its exact-content manifest.

## Closed ambiguities

- The seven scenario families are mandatory strata. The generator may sample
  the declared perturbation families across instances; every individual
  episode is not required to contain all eighteen perturbations. This removes
  the earlier family-specific overclaim without changing the mechanism base.
- `INTEGRITY_VALID` is the umbrella prerequisite for the already defined
  blinding, balance, independence, exact coverage and sealed-referee checks.
  It is not a result verdict.
- Run authorization must bind the digest of a future freeze receipt. A run
  authorization without that exact freeze digest is invalid, preventing the
  former run-authorization/freeze circularity.

## New execution boundary

The result path accepts only the six-action `ActorRequest`/`ActorResponse`
grammar. Qualification `StubActor`, legacy four-action `ProbeAction`, model
aliases and unconfirmed provider revisions fail `NOT_READY`. Provider output is
wrapped in a request/response/revision-bound typed receipt.

The one-shot runner checks C7 before and after bounded execution, verifies the
exact 2,240-row identity set and frozen budgets, rejects hidden referee fields,
and makes an interrupted attempt terminal under the same lock. The scorer may
emit raw loss metrics only and cannot emit `MET`, `NOT_MET`, promotion or route
verdicts. Public runner rows are closed typed identities containing only
family, held-out seed, checkpoint and arm; extra or nested payload/metadata is
rejected before execution.

Readiness is not inferred from well-formed digest strings or a provider's own
revision claim. It requires an exact verified successor manifest plus distinct,
role-separated provider-canary, C7, executor, integrity, freeze and run
authorization receipts. Their subjects bind the corresponding exact artifact,
and an external receipt verifier must validate them. Missing custody keeps the
candidate `NOT_READY`.

## Deliberately unresolved external bindings

- real provider identity, immutable model revision and credential custody;
- real provider canary and 2,240-call budget authorization;
- production C7 binding and independent schema digest;
- sealed executor/result writer and hidden scorer custody;
- future freeze receipt and a separately signed run authorization referencing it.

Until all are bound, this successor remains `NOT_READY / NOT_FROZEN / NOT_RUN`.
