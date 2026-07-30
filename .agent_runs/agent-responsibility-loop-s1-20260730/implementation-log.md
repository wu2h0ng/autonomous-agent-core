# Implementation Log

Exact design authority: `5036ab7ffd6e919d92d66fdd91815523e18b76af`

Implemented the Slice 1 persistence foundation only:

- mandate/workspace/repository/configuration-bound loop lease;
- TTL, heartbeat, clean release, takeover and monotonic fencing;
- fenced SQLite checkpoint recovery;
- stable logical effect keys with durable `PREPARED` / `APPLIED` states;
- fail-closed unknown-effect recovery instead of silent re-execution;
- immutable HCW evaluator root, append-only operator events and receipts;
- canonical accepted-outcome denominator lookup when the settlement ledger exists.

Not implemented in this change:

- `agent run/status/answer/correct/resume`;
- responsibility projection/admission/controller composition;
- Outcome/Help application integration;
- real A-to-B-to-A CLI fixture;
- provider execution or SELFDEV;
- release.

Claim ceiling: `FOUNDATION_IMPLEMENTED_TESTED_LOCAL / PRODUCT_LOOP_NOT_INTEGRATED`.

## Independent-review remediation

The `TECHNICAL_REVISE_FOUNDATION` findings were addressed without connecting
the controller or CLI:

- stable lease identity is now Mandate + tenant + workspace; repository,
  correction, principal, configuration and TTL changes are fail-closed binding
  drift until an inactive, audited explicit rebind;
- non-empty v1 lease/effect/checkpoint tables block startup instead of being
  silently ignored by the v2 schema;
- logical effect keys survive rebind, external callbacks run outside the
  takeover lock, completion uses the trusted store clock, and only a
  content-bound effect/intent receipt envelope may become `APPLIED`;
- expired/taken-over, failed, `PREPARED` and `UNKNOWN` effects require
  reconciliation and cannot be replayed;
- checkpoint authority uses a separate monotonic head row with exact digest
  CAS and closed schema validation, not wall-clock ordering;
- HCW accepted outcomes require a fenced, checkpoint-bound cycle receipt plus
  an exact canonical `SettlementRecord`; a settlement cannot inflate multiple
  cycle denominators;
- a real two-process spawn fixture proves Process B can take over while Process
  A's long external effect resolves only as `UNKNOWN`.

Still excluded: controller/CLI integration, Outcome/Help application
composition, SELFDEV, provider execution, release and any HCW/autonomy claim.
