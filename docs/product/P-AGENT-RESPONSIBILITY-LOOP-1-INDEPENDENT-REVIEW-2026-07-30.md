# P-AGENT-RESPONSIBILITY-LOOP-1 Independent Review

Status: `SPEC_REVISE`

## Evidence identity

- Builder: Codex
- Requested primary reviewer: Claude Code CLI 2.1.185 / Opus
- Primary reviewer attempt: `FAILED_AUTHENTICATION`
- Failure receipt: `401 OAuth access token has been revoked`
- Actual independent reviewer: Kimi Code CLI 0.29.1 / `kimi-code/k3`
- Review mode: read-only
- Base: `27f1643b3ee6fc1404e6f92b39f38d6ea53a5a72`
- Reviewed head: `450be8b3f62ee5826b2cccab03351ebef3077d62`
- Reviewed file SHA-256:
  `f2f55cd7459dcf360d2b4978b21fc54a18ca5f167e30f2d82aa833e1836534c0`
- Diff: one new design file, 408 insertions
- Claim ceiling: design only; no implementation, merge or release claim

Claude did not produce a review and is not credited as reviewer. Kimi was an
explicitly identified replacement and did not edit the reviewed worktree.

## Verdict

`SPEC_REVISE`

There were no P0 findings. Four P1 findings block Slice 1 implementation until
the written design is revised.

## Blocking findings

### P1-1 — Slice 1 depends on Slice 3 gap machinery

The Slice 1 responsibility cycle and acceptance test referenced
`BlueprintGap`, hypothesis budgets, negative-map exclusions and live consumers,
although those contracts were deferred to Slice 3. The `M1 | M2 | M3 | HCW |
PRODUCT_LOOP` field also conflated the three mountains with product-pressure
labels.

Required correction: make Slice 1 select only existing commitments, tasks,
schedules and Help; defer gap-specific admission to Slice 3; bind M1-M3 to the
parent Goal Blueprint and separate product-pressure labels.

### P1-2 — Terminal entry was incorrectly equated with the whole Agent Surface

The statement that Agent CLI is the only product Agent Surface conflicted with
the product blueprint's one logical Ask/Work surface and existing HTTP/UI
channels.

Required correction: define Agent CLI as the sole direct terminal Work entry for
this slice while preserving Ask mode and read-only HTTP/UI projections as
channels of one logical Agent Surface.

### P1-3 — No cross-process lease or fencing

Selection-level atomicity and A-to-B-to-A recovery lacked a durable lease and
fencing token. Two foreground processes, or a stale Process A after Process B
restores, could execute or commit the same responsibility.

Required correction: one durable lease per Mandate/workspace, monotonically
increasing fence, and fence checks at admission and effect commit.

### P1-4 — `WAITING_EVENT` had no wake protocol

The design entered `WAITING_EVENT` without legal wake sources, bounded polling,
status projection or exit conditions.

Required correction: enumerate typed operator input, persisted Help response,
due schedule and correction/revocation as wake sources; prohibit provider calls
and fabricated work while waiting.

## Non-blocking findings

Before their consuming slices or claims:

- declare HCW telemetry and its measurement policy externally governed and
  non-self-modifiable; measure intervention minutes per accepted outcome;
- reconcile the dated Founder challenger-only decision with the older mandatory
  internal-baseline wording before making relative claims;
- specify challenger custody, isolated execution and state-asymmetry semantics;
- bind checkpoint schema version and fail closed on incompatible resume;
- avoid the `MandateSteward` name collision;
- state how Ask-mode chat and `agent run` coexist;
- update CURRENT_STATE only after the revised exact head receives a new review.

## Strengths retained

- the design composes real Mandate, responsibility, Outcome/Help, AgentLoop,
  correction, SQLite and session-recovery substrate rather than inventing a
  parallel runtime;
- it rejects wholesale SELFDEV branch merge, workflow-runner product ownership
  and a premature daemon;
- C7, no-self-approval, evidence-bound settlement, retry exhaustion,
  `HCW_INSUFFICIENT_DATA` and `CHALLENGER_UNAVAILABLE` fail closed;
- Slice 1 keeps SELFDEV as a denied route and makes no autonomy, superiority,
  production or release claim.

## Review boundary

This verdict confirms only the quality and completeness of the reviewed written
design at the exact head and hash above. It does not independently review an
implementation, validate runtime behavior, authorize merge or authorize release.
