## Summary

Stages the Trusted Loop from a partially-wired loop into an end-to-end, governed,
multi-metric production loop. 15 commits, each with tests (TDD) and, where it
changes a contract / public API / safety behavior, an Architecture Review (AR).

Final state: **220 tests pass, `ruff check` clean.**

## What's in here (grouped)

**Governance & safety**
- `fix(trusted-loop): gate connector execution behind approval (hard boundary #4)` — approval-required
  (incl. R4/R5) operations now halt at the new `AWAITING_APPROVAL` state and do NOT invoke the
  side-effecting connector before approval. Previously only safe by accident (sole connector was a no-op).
- `fix(sql-safety): harden SELECT-star detection` — `select distinct *`, `select all *`, `select t.*`
  previously bypassed the star check; now caught, while `count(*)` / `a*b` are not false-flagged. (AR)

**Real data path (ride the data plane)**
- `feat: PR-A real SQL data path via SQLiteQueryExecutor` — stdlib sqlite3 executor injected behind
  `ProviderContract`; the loop runs real SQL against seeded Customer-0 data instead of static rows.

**Back half of the loop (the moat)**
- `feat: real Feedback and KnowledgeAsset builders + stores (PR-B)`
- `feat(trusted-loop): emit KnowledgeAsset candidate to close the back half` — every run sediments a
  DRAFT knowledge candidate bound to the trace.
- `feat(trusted-loop): post-outcome feedback path + OperationTrace in result` — `record_outcome()`
  builds a FeedbackEvent and supersedes the trace's KnowledgeAsset (version bump); `OperationTrace`
  surfaced in the result.

**First real governed write + rollback (L3)**
- `feat(connectors): first real write connector (action_record) + L3 snapshot/rollback` — a real,
  reversible write connector that actually exercises the governance gate, pre-execution snapshot
  (`SnapshotStore`), and `runtime.rollback(snapshot_id)`.

**Trigger surfaces**
- `feat(api): record_outcome trigger surfaces (CLI subcommand + FastAPI)` — shared framework-agnostic
  service; `POST /runs` + `POST /outcomes` with an `X-API-Key` auth boundary (503 if unconfigured,
  401 if wrong); fastapi/httpx are an optional `[http]` extra (bare-env CI stays green).

**Evaluation**
- `feat(eval-hub): lightweight Eval threshold report` — per-dimension pass-rate vs thresholds, wired
  into the golden eval.

**Multi-metric + unified failure contract**
- `feat(trusted-loop): multi-metric query via template selection (P0-2)` — `TemplateRegistry` selects
  the SQL template by resolved metric (no more "ask roi, run gmv SQL, label roi"). (AR)
- `feat(trusted-loop): unified failure/block result contract` — `BlockCode` / `TrustedLoopBlock` /
  `TrustedLoopOutcome` + `TrustedLoopBlocked`; `evaluate()` returns a unified ok|blocked outcome;
  surfaces map blocks to a structured response (HTTP 422, CLI non-zero). (AR)
- `feat(domain-pack): roi + conversion_rate templates and visits seed column` — content_commerce now
  serves gmv / spend / roi / conversion_rate end-to-end.

## Verification

- `python -m unittest discover -s tests` → 220 passed; `ruff check .` clean; touched files
  `ruff format --check` clean. (HTTP tests skip in a bare env; ran green with fastapi/httpx installed.)
- CLI smokes (real sqlite provider): gmv/spend/roi return real values; unknown metric → structured block.

## Review focus

- `packages/os_core/src/agent_os_core/trusted_loop.py` — the orchestrator (governance gate, template
  selection, block sites, `evaluate`, `record_outcome`, `rollback`).
- The three ARs under `docs/architecture_reviews/AR-20260606-*`.
- Boundary check: OS Core imports no `domain_packs`/`providers`/`action_connectors`.

## Known follow-ups (not in this PR)

- Stores are in-memory; cross-session feedback/knowledge needs a persistent (PG) store.
- When ActionProposalBuilder should route to a real write connector is an open product decision.
- L3 snapshot store → PG JSONB; L4 workflow compensation (Temporal).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
